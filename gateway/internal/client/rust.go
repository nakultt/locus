package client

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

type RustClient struct {
	BaseURL    string
	httpClient *http.Client
}

func NewRustClient(baseURL string) *RustClient {
	return &RustClient{
		BaseURL: baseURL,
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

type StoreCredentialsRequest struct {
	UserID          string `json:"user_id"`
	Provider        string `json:"provider"`
	CredentialsJSON string `json:"credentials_json"`
}

func (c *RustClient) StoreOAuthCredentials(ctx context.Context, req StoreCredentialsRequest) error {
	bodyBytes, err := json.Marshal(req)
	if err != nil {
		return err
	}

	url := fmt.Sprintf("%s/api/users/%s/integrations", c.BaseURL, req.UserID)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewBuffer(bodyBytes))
	if err != nil {
		return err
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		return fmt.Errorf("rust service returned status: %d", resp.StatusCode)
	}

	return nil
}
