package config

import (
	"log"

	"github.com/kelseyhightower/envconfig"
)

type Config struct {
	RustServiceURL     string `envconfig:"RUST_SERVICE_URL" required:"true"`
	PythonServiceURL   string `envconfig:"PYTHON_SERVICE_URL" required:"true"`
	JWTSecret          string `envconfig:"JWT_SECRET" required:"true"`
	GoogleClientID     string `envconfig:"GOOGLE_CLIENT_ID"`
	GoogleClientSecret string `envconfig:"GOOGLE_CLIENT_SECRET"`
	GoogleRedirectURI  string `envconfig:"GOOGLE_REDIRECT_URI" default:"http://localhost:8080/auth/google/callback"`
	LinearClientID     string `envconfig:"LINEAR_CLIENT_ID"`
	LinearClientSecret string `envconfig:"LINEAR_CLIENT_SECRET"`
	LinearRedirectURI  string `envconfig:"LINEAR_REDIRECT_URI" default:"http://localhost:8080/auth/linear/callback"`
	FrontendURL        string `envconfig:"FRONTEND_URL" default:"http://localhost:3000"`
	LogLevel           string `envconfig:"LOG_LEVEL" default:"info"`
	Port               string `envconfig:"PORT" default:"8080"`
}

func Load() *Config {
	var cfg Config
	if err := envconfig.Process("", &cfg); err != nil {
		log.Fatalf("Failed to process env config: %v", err)
	}
	return &cfg
}
