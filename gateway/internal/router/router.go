package router

import (
	"github.com/go-chi/chi/v5"
	chimiddleware "github.com/go-chi/chi/v5/middleware"
	"github.com/go-chi/cors"
	"github.com/nakultt/locus/gateway/internal/client"
	"github.com/nakultt/locus/gateway/internal/config"
	"github.com/nakultt/locus/gateway/internal/handler"
	"github.com/nakultt/locus/gateway/internal/middleware"
)

func New(cfg *config.Config, rustClient *client.RustClient, pythonClient *client.PythonClient) *chi.Mux {
	r := chi.NewRouter()

	// Base middleware
	r.Use(middleware.RequestID)
	r.Use(chimiddleware.RealIP)
	r.Use(middleware.Logger)
	r.Use(chimiddleware.Recoverer)
	r.Use(cors.Handler(cors.Options{
		AllowedOrigins:   []string{cfg.FrontendURL},
		AllowedMethods:   []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Accept", "Authorization", "Content-Type", "X-CSRF-Token"},
		ExposedHeaders:   []string{"Link"},
		AllowCredentials: true,
		MaxAge:           300,
	}))

	r.Get("/health", handler.HealthCheck())

	// Proxy to Rust for Auth
	rustProxy := handler.NewProxy(cfg.RustServiceURL)
	r.Handle("/auth/register", rustProxy)
	r.Handle("/auth/register/*", rustProxy)
	r.Handle("/auth/login", rustProxy)
	r.Handle("/auth/login/*", rustProxy)
	r.Handle("/auth/user", rustProxy)
	r.Handle("/auth/user/*", rustProxy)

	// Protected routes
	r.Group(func(r chi.Router) {
		r.Use(middleware.JWTAuth(cfg.JWTSecret))

		// OAuth flows (Requires auth to associate with user)
		oauthHandler := handler.NewOAuthHandler(cfg, rustClient)
		r.Get("/auth/google/login", oauthHandler.GoogleLogin())
		r.Get("/auth/google/callback", oauthHandler.GoogleCallback())
		r.Get("/auth/linear/login", oauthHandler.LinearLogin())
		r.Get("/auth/linear/callback", oauthHandler.LinearCallback())

		// API routes to Rust
		r.Handle("/api/users", rustProxy)
		r.Handle("/api/users/*", rustProxy)
		
		// API routes to Python (chat)
		pythonProxy := handler.NewProxy(cfg.PythonServiceURL)
		r.Handle("/api/chat", pythonProxy)
		r.Handle("/api/chat/*", pythonProxy)
		r.Handle("/api/supported-commands", pythonProxy)
		r.Handle("/api/supported-commands/*", pythonProxy)
	})

	return r
}
