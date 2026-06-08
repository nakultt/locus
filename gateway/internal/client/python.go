package client

import (
	"net/http"
	"time"
)

type PythonClient struct {
	BaseURL    string
	httpClient *http.Client
}

func NewPythonClient(baseURL string) *PythonClient {
	return &PythonClient{
		BaseURL: baseURL,
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}
