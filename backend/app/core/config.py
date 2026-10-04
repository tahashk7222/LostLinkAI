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
    # Production photo storage. When all three are set, photos go to Cloudinary (authenticated, never publicly
    # delivered). Leave them empty for local development: photos then stay on the local filesystem.
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    match_threshold: float = 0.55
    # Visual evidence. 'onnx' = learned embedding model (falls back to the heuristic if it cannot load);
    # 'heuristic' = the colour-histogram + difference-hash method only. See docs/VISION.md.
    vision_enabled: bool = True
    vision_provider: str = "onnx"
    vision_model_path: str = "models/vision/mobilenetv2-7-pooled.onnx"  # relative to backend/
    vision_device: str = "auto"  # auto | cpu | cuda
    # Optional path to a different geographic boundary file (default: app/geo/uet_lahore.json)
    geofence_file: str = ""
    admin_email: str = ""
    admin_password: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def cloudinary_configured(self) -> bool:
        return bool(self.cloudinary_cloud_name and self.cloudinary_api_key and self.cloudinary_api_secret)

    @model_validator(mode="after")
    def _require_secret_in_production(self):
        if self.app_env == "production" and (self.jwt_secret == "change-me" or len(self.jwt_secret) < 32):
            raise ValueError("JWT_SECRET must be set to a strong value in production")
        return self

    @model_validator(mode="after")
    def _require_cloud_storage_in_production(self):
        # The free hosting disk is wiped on restart, so production photos must go to Cloudinary.
        if self.app_env == "production" and not self.cloudinary_configured:
            raise ValueError("Cloudinary is required for photo storage in production "
                             "(set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
