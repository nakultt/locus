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
		AllowedOrigins:   []string{"http://localhost:3000", "http://localhost:8080", cfg.FrontendURL},
		AllowedMethods:   []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Accept", "Authorization", "Content-Type", "X-CSRF-Token"},
		ExposedHeaders:   []string{"Link"},
		AllowCredentials: true,
		MaxAge:           300,
	}))

	r.Get("/health", handler.HealthCheck())

	// Proxy to Rust for Auth API
	rustProxy := handler.NewProxy(cfg.RustServiceURL)
	r.Post("/auth/register", rustProxy.ServeHTTP)
	r.Post("/auth/register/*", rustProxy.ServeHTTP)
	r.Post("/auth/login", rustProxy.ServeHTTP)
	r.Post("/auth/login/*", rustProxy.ServeHTTP)
	r.Handle("/auth/user", rustProxy)
	r.Handle("/auth/user/*", rustProxy)

	// OAuth flows (Requires auth to associate with user)
	oauthHandler := handler.NewOAuthHandler(cfg, rustClient)
	
	// Public OAuth login initiators
	r.Get("/auth/google", oauthHandler.GoogleLogin())
	r.Get("/auth/linear", oauthHandler.LinearLogin())

	// Protected routes
	r.Group(func(r chi.Router) {
		r.Use(middleware.JWTAuth(cfg.JWTSecret))

		// OAuth callback APIs
		r.Get("/api/auth/google/callback", oauthHandler.GoogleCallback())
		r.Get("/api/auth/linear/callback", oauthHandler.LinearCallback())

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

	// Proxy all unhandled routes to the frontend
	frontendProxy := handler.NewProxy(cfg.FrontendURL)
	r.NotFound(frontendProxy.ServeHTTP)
	r.MethodNotAllowed(frontendProxy.ServeHTTP)

	return r
}
