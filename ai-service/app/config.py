from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    google_api_key: str = ""
    ollama_base_url: str = "http://host.docker.internal:11434"
    llm_provider: str = "gemini"  # "gemini" or "ollama"
    ollama_model: str = "qwen3.5:4b"
    rust_service_url: str = "http://perf-engine:8081"
    log_level: str = "info"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
