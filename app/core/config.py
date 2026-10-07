"""Application settings loaded from environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Values are read from environment variables (or a local ``.env`` file) and
    fall back to sensible defaults for local development.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    upload_dir: Path = Path("./uploads")
    database_url: str = "sqlite:///./geospatial.db"
    max_upload_bytes: int = 200 * 1024 * 1024  # 200 MB

    # ID generator config — Crockford-style base32, no I/L/O/U to avoid confusion.
    id_alphabet: str = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    id_length: int = 10


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a cached Settings instance."""

    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return _settings
