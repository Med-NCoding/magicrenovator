from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_ENV: Literal["development", "staging", "production", "test"] = "development"
    GATEWAY_MODE: Literal["live"] = "live"
    DATABASE_URL: str = "postgresql://localhost/renopreview"
    REDIS_URL: str = "redis://localhost:6379/0"
    ASSET_BUCKET: str = str(_REPO_ROOT / ".local_private_assets")
    SESSION_SIGNING_SECRET: str = "dev-only-session-signing-secret-32b"
    CREDENTIAL_ENCRYPTION_KEY: str = "dev-only-credential-encrypt-key-32b"
    ACCOUNT_FINGERPRINT_SECRET: str = "dev-only-account-fingerprint-key-32b"
    MAGIC_HOUR_BASE_URL: str = "https://api.magichour.ai/v1"
    MODEL_CATALOG_PATH: str = "config/model-catalog.json"
    MAX_UPLOAD_BYTES: int = 15728640
    MAX_IMAGE_PIXELS: int = 24000000
    MAX_ROOMS_PER_PROJECT: int = 5
    MAX_ACTIVE_JOBS_PER_ACCOUNT: int = 1
    MAX_WORKFLOW_CREDITS: int = 2500
    CREDENTIAL_TTL_SECONDS: int = 86400
    CREDENTIAL_IDLE_SECONDS: int = 7200
    ANONYMOUS_RETENTION_DAYS: int = 7
    SIGNED_URL_TTL_SECONDS: int = 86400
    PAUSE_GENERATIONS: bool = False
    ALLOWED_DOWNLOAD_HOSTS: str = "videos.magichour.ai,assets.magichour.ai,cdn.magichour.ai"

    @model_validator(mode="after")
    def validate_security_invariants(self) -> "Settings":
        placeholders = {
            "replace-through-secret-manager",
            "configured-locally",
            "",
        }
        if self.APP_ENV in {"staging", "production"}:
            for field_name in (
                "SESSION_SIGNING_SECRET",
                "CREDENTIAL_ENCRYPTION_KEY",
                "ACCOUNT_FINGERPRINT_SECRET",
            ):
                val = getattr(self, field_name)
                if val in placeholders or val.startswith("dev-only-") or len(val) < 24:
                    raise ValueError(
                        f"{field_name} must be replaced with a strong deployment secret in {self.APP_ENV}"
                    )
            if "configured-locally" in self.DATABASE_URL or "configured-locally" in self.REDIS_URL:
                raise ValueError("DATABASE_URL and REDIS_URL must not use placeholder values in production")
        if not self.MAGIC_HOUR_BASE_URL.startswith("https://api.magichour.ai"):
            raise ValueError("MAGIC_HOUR_BASE_URL must point to trusted Magic Hour host")
        return self

    def resolved_catalog_path(self) -> Path:
        p = Path(self.MODEL_CATALOG_PATH)
        if p.is_absolute() and p.exists():
            return p
        candidate = _REPO_ROOT / self.MODEL_CATALOG_PATH
        if candidate.exists():
            return candidate
        return Path(__file__).resolve().parents[1] / self.MODEL_CATALOG_PATH

    def resolved_asset_dir(self) -> Path:
        p = Path(self.ASSET_BUCKET)
        if not p.is_absolute():
            p = _REPO_ROOT / ".local_private_assets" / self.ASSET_BUCKET
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def storage_path(self) -> Path:
        return self.resolved_asset_dir()


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_cache() -> Settings:
    global _settings
    _settings = Settings()
    return _settings
