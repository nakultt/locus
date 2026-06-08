package handler

import (
	"net/http"
	"net/http/httputil"
	"net/url"
)

func NewProxy(targetURL string) http.Handler {
	target, _ := url.Parse(targetURL)
	proxy := httputil.NewSingleHostReverseProxy(target)

	// Keep the original path and query parameters
	originalDirector := proxy.Director
	proxy.Director = func(req *http.Request) {
		originalDirector(req)
		// We deliberately DO NOT override req.Host so that Next.js knows the correct public URL
		req.Header.Set("X-Forwarded-Host", req.Host)
		req.Header.Set("X-Forwarded-Proto", "http")
	}

	return proxy
}
