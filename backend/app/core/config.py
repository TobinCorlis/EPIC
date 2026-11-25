import json
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "EPIC"
    app_env: str = "development"
    database_url: str = "sqlite:///./epic.db"
    secret_key: str = "development-only-change-me"
    session_hours: int = 168
    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:8000"]
    trusted_hosts: Annotated[list[str], NoDecode] = ["localhost", "127.0.0.1", "testserver"]
    auto_create_schema: bool = True
    worker_poll_seconds: float = 1.0
    worker_max_attempts: int = 3
    enforce_authorization: bool = False
    referee_llm_base_url: str = ""
    referee_llm_api_key: str = ""
    referee_llm_model: str = ""
    factcheck_contact_email: str = "factcheck@epic.local"
    factcheck_timeout_seconds: float = 10.0
    factcheck_retries: int = 2
    factcheck_min_interval_seconds: float = 1.0
    factcheck_cache_hours: int = 24
    factcheck_recheck_days: int = 30
    factcheck_save_page_now: bool = False
    factcheck_auto_run: bool = True
    factcheck_llm_base_url: str = ""
    factcheck_llm_api_key: str = ""
    factcheck_llm_model: str = ""
    courtlistener_api_token: str = ""
    govinfo_api_key: str = ""
    support_score_threshold: float = 0.6
    factcheck_lead_min_overlap: float = 0.25
    factcheck_lead_limit: int = 3
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("allowed_origins", "trusted_hosts", mode="before")
    @classmethod
    def parse_string_list(cls, value):
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                parsed = json.loads(text)
                if not isinstance(parsed, list):
                    raise ValueError("expected a JSON list")
                return [str(item).strip() for item in parsed if str(item).strip()]
            return [item.strip() for item in text.split(",") if item.strip()]
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
