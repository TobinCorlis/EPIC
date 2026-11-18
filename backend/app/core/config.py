from functools import lru_cache
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "EPIC"
    app_env: str = "development"
    database_url: str = "sqlite:///./epic.db"
    secret_key: str = "development-only-change-me"
    session_hours: int = 168
    allowed_origins: list[str] = ["http://localhost:8000"]
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    auto_create_schema: bool = True
    worker_poll_seconds: float = 1.0
    worker_max_attempts: int = 3
    enforce_authorization: bool = False
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("allowed_origins", "trusted_hosts", mode="before")
    @classmethod
    def split_csv(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def validate_production(self):
        if self.app_env.lower() == "production":
            errors = []
            if self.database_url.startswith("sqlite"):
                errors.append("DATABASE_URL must use PostgreSQL in production")
            if self.secret_key == "development-only-change-me" or len(self.secret_key) < 32:
                errors.append("SECRET_KEY must be changed and contain at least 32 characters")
            if "*" in self.allowed_origins:
                errors.append("ALLOWED_ORIGINS cannot contain '*' in production")
            if not self.enforce_authorization:
                errors.append("ENFORCE_AUTHORIZATION must be true in production")
            if self.auto_create_schema:
                errors.append("AUTO_CREATE_SCHEMA must be false in production; use migrations")
            if errors:
                raise ValueError("; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
