from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    client_url: str = "http://localhost:5173"

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "interviewlab"

    jwt_secret: str = "dev-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7

    invite_link_base_url: str = "http://localhost:5173/test"

    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-5"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
