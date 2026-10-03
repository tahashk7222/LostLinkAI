from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 120

    database_url: str = "sqlite:///./lostlink.db"
    cors_origins: str = "http://localhost:3000"

    storage_dir: str = "./storage"
    max_upload_mb: int = 5

    match_threshold: float = 0.55
    # Optional path to a different geographic boundary file (default: app/geo/uet_lahore.json)
    geofence_file: str = ""
    admin_email: str = ""
    admin_password: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _require_secret_in_production(self):
        if self.app_env == "production" and (self.jwt_secret == "change-me" or len(self.jwt_secret) < 32):
            raise ValueError("JWT_SECRET must be set to a strong value in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
