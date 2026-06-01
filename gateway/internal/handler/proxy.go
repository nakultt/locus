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
		req.Host = target.Host // Some servers need the host header to match
	}

	return proxy
}
