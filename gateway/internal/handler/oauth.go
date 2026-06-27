package handler

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/nakultt/locus/gateway/internal/client"
	"github.com/nakultt/locus/gateway/internal/config"
	"github.com/nakultt/locus/gateway/internal/middleware"
)

type OAuthHandler struct {
	cfg        *config.Config
	rustClient *client.RustClient
}

func NewOAuthHandler(cfg *config.Config, rustClient *client.RustClient) *OAuthHandler {
	return &OAuthHandler{
		cfg:        cfg,
		rustClient: rustClient,
	}
}

func (h *OAuthHandler) GoogleLogin() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		token := r.URL.Query().Get("token")
		action := r.URL.Query().Get("action")
		service := r.URL.Query().Get("service")
		
		state := token
		if action == "login" {
			state = "login"
		} else if service != "" {
			state = service
		}

		scopes := "email profile"
		if service == "gmail" {
			scopes += " https://www.googleapis.com/auth/gmail.modify"
		} else if service == "calendar" {
			scopes += " https://www.googleapis.com/auth/calendar"
		} else if service == "docs" || service == "sheets" || service == "slides" || service == "drive" {
			scopes += " https://www.googleapis.com/auth/drive"
		} else if service == "forms" {
			scopes += " https://www.googleapis.com/auth/drive"
		}

		encodedScopes := url.QueryEscape(scopes)

		authURL := fmt.Sprintf("https://accounts.google.com/o/oauth2/v2/auth?client_id=%s&redirect_uri=%s&response_type=code&scope=%s&state=%s&access_type=offline&prompt=consent", h.cfg.GoogleClientID, url.QueryEscape(h.cfg.GoogleRedirectURI), encodedScopes, url.QueryEscape(state))
		http.Redirect(w, r, authURL, http.StatusTemporaryRedirect)
	}
}

func (h *OAuthHandler) exchangeGoogleToken(code string) ([]byte, error) {
	data := url.Values{}
	data.Set("client_id", h.cfg.GoogleClientID)
	data.Set("client_secret", h.cfg.GoogleClientSecret)
	data.Set("code", code)
	data.Set("grant_type", "authorization_code")
	data.Set("redirect_uri", h.cfg.GoogleRedirectURI)

	req, err := http.NewRequest("POST", "https://oauth2.googleapis.com/token", strings.NewReader(data.Encode()))
	if err != nil {
		return nil, err
	}
	req.Header.Add("Content-Type", "application/x-www-form-urlencoded")

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("failed to exchange token: %s", string(bodyBytes))
	}

	return io.ReadAll(resp.Body)
}

func (h *OAuthHandler) GoogleCallback() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		code := r.URL.Query().Get("code")
		state := r.URL.Query().Get("state")
		if code == "" {
			http.Error(w, "missing code", http.StatusBadRequest)
			return
		}

		tokenBytes, err := h.exchangeGoogleToken(code)
		if err != nil {
			http.Error(w, fmt.Sprintf("failed to exchange token: %v", err), http.StatusInternalServerError)
			return
		}

		userID := middleware.UserIDFromContext(r.Context())
		if userID == "" {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}

		provider := "google"
		if state != "" && state != "login" {
			provider = state
		}

		// Inject obtained_at into the token
		var tokenMap map[string]interface{}
		if err := json.Unmarshal(tokenBytes, &tokenMap); err == nil {
			tokenMap["obtained_at"] = time.Now().UTC().Format(time.RFC3339)
			if updatedBytes, err := json.Marshal(tokenMap); err == nil {
				tokenBytes = updatedBytes
			}
		}

		err = h.rustClient.StoreOAuthCredentials(context.Background(), client.StoreCredentialsRequest{
			UserID:          userID,
			Provider:        provider,
			CredentialsJSON: string(tokenBytes),
		})

		if err != nil {
			http.Error(w, "failed to store credentials", http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "success", "provider": provider})
	}
}

func (h *OAuthHandler) fetchGoogleUserInfo(accessToken string) (map[string]interface{}, error) {
	req, err := http.NewRequest("GET", "https://www.googleapis.com/oauth2/v2/userinfo", nil)
	if err != nil {
		return nil, err
	}
	req.Header.Add("Authorization", "Bearer "+accessToken)

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("failed to fetch user info: %s", string(bodyBytes))
	}

	var userInfo map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&userInfo); err != nil {
		return nil, err
	}
	return userInfo, nil
}

func (h *OAuthHandler) GoogleLoginCallback() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		code := r.URL.Query().Get("code")
		if code == "" {
			http.Error(w, "missing code", http.StatusBadRequest)
			return
		}

		tokenBytes, err := h.exchangeGoogleToken(code)
		if err != nil {
			http.Error(w, fmt.Sprintf("failed to exchange token: %v", err), http.StatusInternalServerError)
			return
		}

		var tokenResp map[string]interface{}
		json.Unmarshal(tokenBytes, &tokenResp)
		accessToken, ok := tokenResp["access_token"].(string)
		if !ok {
			http.Error(w, "failed to get access token from google", http.StatusInternalServerError)
			return
		}

		userInfo, err := h.fetchGoogleUserInfo(accessToken)
		if err != nil {
			http.Error(w, fmt.Sprintf("failed to fetch user info: %v", err), http.StatusInternalServerError)
			return
		}

		email, _ := userInfo["email"].(string)
		name, _ := userInfo["name"].(string)
		if name == "" {
			name = "Google User"
		}

		if email == "" {
			http.Error(w, "google account has no email", http.StatusBadRequest)
			return
		}

		// Proxy this to Rust /auth/google
		rustReqBody, _ := json.Marshal(map[string]string{
			"email": email,
			"name":  name,
		})

		rustReq, err := http.NewRequest("POST", h.cfg.RustServiceURL+"/auth/google", bytes.NewReader(rustReqBody))
		if err != nil {
			http.Error(w, "failed to create rust request", http.StatusInternalServerError)
			return
		}
		rustReq.Header.Set("Content-Type", "application/json")

		client := &http.Client{Timeout: 10 * time.Second}
		rustResp, err := client.Do(rustReq)
		if err != nil {
			http.Error(w, "failed to call rust backend", http.StatusInternalServerError)
			return
		}
		defer rustResp.Body.Close()

		if rustResp.StatusCode != http.StatusOK {
			rustBody, _ := io.ReadAll(rustResp.Body)
			http.Error(w, fmt.Sprintf("rust auth failed: %s", string(rustBody)), rustResp.StatusCode)
			return
		}

		// Forward Rust response to frontend
		w.Header().Set("Content-Type", "application/json")
		io.Copy(w, rustResp.Body)
	}
}

func (h *OAuthHandler) LinearLogin() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		token := r.URL.Query().Get("token")
		url := fmt.Sprintf("https://linear.app/oauth/authorize?client_id=%s&redirect_uri=%s&response_type=code&scope=read&state=%s", h.cfg.LinearClientID, h.cfg.LinearRedirectURI, token)
		http.Redirect(w, r, url, http.StatusTemporaryRedirect)
	}
}

func (h *OAuthHandler) exchangeLinearToken(code string) ([]byte, error) {
	data := url.Values{}
	data.Set("client_id", h.cfg.LinearClientID)
	data.Set("client_secret", h.cfg.LinearClientSecret)
	data.Set("code", code)
	data.Set("grant_type", "authorization_code")
	data.Set("redirect_uri", h.cfg.LinearRedirectURI)

	req, err := http.NewRequest("POST", "https://api.linear.app/oauth/token", strings.NewReader(data.Encode()))
	if err != nil {
		return nil, err
	}
	req.Header.Add("Content-Type", "application/x-www-form-urlencoded")

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("failed to exchange linear token: %s", string(bodyBytes))
	}

	return io.ReadAll(resp.Body)
}

func (h *OAuthHandler) LinearCallback() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		code := r.URL.Query().Get("code")
		if code == "" {
			http.Error(w, "missing code", http.StatusBadRequest)
			return
		}

		tokenBytes, err := h.exchangeLinearToken(code)
		if err != nil {
			http.Error(w, fmt.Sprintf("failed to exchange token: %v", err), http.StatusInternalServerError)
			return
		}

		userID := middleware.UserIDFromContext(r.Context())
		if userID == "" {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}

		err = h.rustClient.StoreOAuthCredentials(context.Background(), client.StoreCredentialsRequest{
			UserID:          userID,
			Provider:        "linear",
			CredentialsJSON: string(tokenBytes),
		})

		if err != nil {
			http.Error(w, "failed to store credentials", http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "success", "provider": "linear"})
	}
}
