from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://fitlife:fitlife@localhost:5434/fitlife"
    jwt_secret: str = "development-only-change-me"
    jwt_expires_minutes: int = 10080
    llm_base_url: str = "http://localhost:11434"
    llm_model: str = "llama3.2:3b"
    llm_timeout_seconds: int = 45
    vector_db_path: str = "/tmp/fitlife-vectors"
    cors_origins: str = "http://localhost:5180"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

