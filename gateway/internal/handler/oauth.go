package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"

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
		// Mock implementation for Google OAuth redirect
		url := fmt.Sprintf("https://accounts.google.com/o/oauth2/v2/auth?client_id=%s&redirect_uri=%s&response_type=code&scope=email", h.cfg.GoogleClientID, h.cfg.GoogleRedirectURI)
		http.Redirect(w, r, url, http.StatusTemporaryRedirect)
	}
}

func (h *OAuthHandler) GoogleCallback() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		code := r.URL.Query().Get("code")
		if code == "" {
			http.Error(w, "missing code", http.StatusBadRequest)
			return
		}

		// Mock token exchange
		// In a real implementation, you would exchange the code for an access token here.
		mockToken := `{"access_token": "mock_google_token"}`

		userID := middleware.UserIDFromContext(r.Context())
		if userID == "" {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}

		err := h.rustClient.StoreOAuthCredentials(context.Background(), client.StoreCredentialsRequest{
			UserID:          userID,
			Provider:        "google",
			CredentialsJSON: mockToken,
		})

		if err != nil {
			http.Error(w, "failed to store credentials", http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "success", "provider": "google"})
	}
}

func (h *OAuthHandler) LinearLogin() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Mock implementation for Linear OAuth redirect
		url := fmt.Sprintf("https://linear.app/oauth/authorize?client_id=%s&redirect_uri=%s&response_type=code&scope=read", h.cfg.LinearClientID, h.cfg.LinearRedirectURI)
		http.Redirect(w, r, url, http.StatusTemporaryRedirect)
	}
}

func (h *OAuthHandler) LinearCallback() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		code := r.URL.Query().Get("code")
		if code == "" {
			http.Error(w, "missing code", http.StatusBadRequest)
			return
		}

		// Mock token exchange
		mockToken := `{"access_token": "mock_linear_token"}`

		userID := middleware.UserIDFromContext(r.Context())
		if userID == "" {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}

		err := h.rustClient.StoreOAuthCredentials(context.Background(), client.StoreCredentialsRequest{
			UserID:          userID,
			Provider:        "linear",
			CredentialsJSON: mockToken,
		})

		if err != nil {
			http.Error(w, "failed to store credentials", http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "success", "provider": "linear"})
	}
}
