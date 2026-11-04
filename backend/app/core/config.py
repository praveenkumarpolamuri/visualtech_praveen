from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "VisualTech API"
    environment: str = "development"
    database_url: str = "sqlite:///./visualtech.db"
    cors_origins: str = "http://localhost:3000"
    jwt_secret: str = "change-this-jwt-secret-in-production"
    access_token_expire_minutes: int = 60
    bootstrap_admin_email: str = "admin@visualtech.local"
    bootstrap_admin_password: str = "change-me"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    ollama_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3.2:3b"
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "visualtech-media"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
