package middleware

import (
	"log/slog"
	"net/http"
	"time"
)

func Logger(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()

		// create a wrapper to capture status code
		ww := &responseWriterWrapper{ResponseWriter: w, status: 200}

		next.ServeHTTP(ww, r)

		duration := time.Since(start)
		reqID := r.Context().Value(RequestIDKey)
		
		slog.Info("Request handled",
			"method", r.Method,
			"path", r.URL.Path,
			"status", ww.status,
			"duration", duration,
			"req_id", reqID,
		)
	})
}

type responseWriterWrapper struct {
	http.ResponseWriter
	status int
}

func (ww *responseWriterWrapper) WriteHeader(status int) {
	ww.status = status
	ww.ResponseWriter.WriteHeader(status)
}
