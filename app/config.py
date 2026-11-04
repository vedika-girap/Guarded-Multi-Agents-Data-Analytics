from functools import lru_cache
import logging
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, SecretStr, ValidationError, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "demo.db"
MAX_ROWS = 100
ROLE_LEVELS = {"viewer": 0, "analyst": 1, "admin": 2}


class Settings(BaseSettings):
    """Central configuration. Process environment takes precedence over .env."""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "staging", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("APP_ENV", "ENVIRONMENT"),
    )
    auth_mode: Literal["dev", "jwt"] = "dev"
    demo_mode: bool = Field(default=True, validation_alias="DEMO_MODE")
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.8-flash"
    gemini_embedding_model: str = "gemini-embedding-001"
    llm_max_output_tokens: int = Field(default=700, gt=0, le=8192)
    demo_requests_per_minute: int = Field(default=10, gt=0, validation_alias="DEMO_REQUESTS_PER_MINUTE")
    demo_max_question_length: int = Field(default=400, gt=0, le=1000, validation_alias="DEMO_MAX_QUESTION_LENGTH")
    demo_max_rows: int = Field(default=25, gt=0, le=100, validation_alias="DEMO_MAX_ROWS")
    demo_request_timeout_seconds: float = Field(default=10, gt=0, le=120, validation_alias="DEMO_REQUEST_TIMEOUT_SECONDS")
    demo_max_output_tokens: int = Field(default=256, gt=0, le=8192, validation_alias="DEMO_MAX_OUTPUT_TOKENS")

    database_url: str = "sqlite:///data/demo.db"
    migration_database_url: str | None = None
    database_statement_timeout_ms: int = Field(default=5000, gt=0)
    viewer_min_group_size: int = Field(default=3, ge=2)

    # >>> ACTION REQUIRED (Stage 1): Set all three JWT variables when AUTH_MODE=jwt.
    # See README section "Setup checklist".
    auth_jwt_secret: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("JWT_SECRET", "AUTH_JWT_SECRET"),
    )
    # >>> ACTION REQUIRED (Stage 1): Set the exact issuer and audience used by your identity provider.
    # See README section "Setup checklist".
    auth_jwt_issuer: str | None = None
    auth_jwt_audience: str | None = None

    dev_rate_limit_per_minute: int = Field(default=120, gt=0)
    staging_rate_limit_per_minute: int = Field(default=60, gt=0)
    production_rate_limit_per_minute: int = Field(default=30, gt=0)
    dev_max_question_tokens: int = Field(default=4096, gt=0)
    staging_max_question_tokens: int = Field(default=2048, gt=0)
    production_max_question_tokens: int = Field(default=2048, gt=0)
    rate_limit_redis_url: str | None = None
    rate_limit_redis_timeout_seconds: float = Field(default=0.5, gt=0, le=10, validation_alias="RATE_LIMIT_REDIS_TIMEOUT_SECONDS")

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> "Settings":
        if self.environment == "production" and self.auth_mode == "dev" and not self.demo_mode:
            raise ValueError("AUTH_MODE=dev is forbidden when ENVIRONMENT=production; configure AUTH_MODE=jwt.")
        if self.environment == "production" and not self.rate_limit_redis_url:
            raise ValueError("RATE_LIMIT_REDIS_URL is required in production for shared rate limiting.")

        if self.auth_mode == "jwt" or self.demo_mode:
            missing = [
                "JWT_SECRET" if self.demo_mode else "AUTH_JWT_SECRET"
                for value in (self.auth_jwt_secret,)
                if value is None
            ]
            if self.auth_mode == "jwt" and not self.demo_mode:
                missing.extend(
                    name for name, value in (
                        ("AUTH_JWT_ISSUER", self.auth_jwt_issuer),
                        ("AUTH_JWT_AUDIENCE", self.auth_jwt_audience),
                    ) if value is None or (isinstance(value, str) and not value.strip())
                )
            if missing:
                raise ValueError(
                    "Missing required JWT settings: " + ", ".join(missing)
                    + ". Set them in .env or the process environment; see README section 'Setup checklist'."
                )
            assert self.auth_jwt_secret is not None
            if (
                len(self.auth_jwt_secret.get_secret_value().encode("utf-8")) < 32
                and self.environment in {"staging", "production"}
            ):
                raise ValueError("JWT_SECRET/AUTH_JWT_SECRET must be at least 32 bytes for HS256.")
        return self

    @property
    def rate_limit_per_minute(self) -> int:
        return {
            "development": self.dev_rate_limit_per_minute,
            "staging": self.staging_rate_limit_per_minute,
            "production": self.production_rate_limit_per_minute,
        }[self.environment]

    @property
    def max_question_tokens(self) -> int:
        return {
            "development": self.dev_max_question_tokens,
            "staging": self.staging_max_question_tokens,
            "production": self.production_max_question_tokens,
        }[self.environment]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def validate_runtime_settings() -> Settings:
    """Resolve settings during app startup so configuration errors are actionable."""
    try:
        settings = get_settings()
    except ValidationError as exc:
        messages = [str(error["msg"]).removeprefix("Value error, ") for error in exc.errors()]
        raise RuntimeError("Configuration error: " + "; ".join(messages)) from None
    if (
        (settings.auth_mode == "jwt" or settings.demo_mode)
        and settings.environment == "development"
        and settings.auth_jwt_secret is not None
        and len(settings.auth_jwt_secret.get_secret_value().encode("utf-8")) < 32
    ):
        logging.getLogger(__name__).warning(
            "JWT_SECRET is shorter than 32 bytes; use a 32-byte or longer secret outside local development."
        )
    return settings
