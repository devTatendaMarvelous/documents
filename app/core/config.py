"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _project_root() -> Path:
    """Return the project root directory (documents/)."""
    return Path(__file__).resolve().parents[2]


def parse_size(value: str | int) -> int:
    """
    Parse a human-readable size string into bytes.

    Supports bare integers and suffixes: B, KB, MB, GB (case-insensitive).
    Examples: ``50MB``, ``1024``, ``1.5GB``.
    """
    if isinstance(value, int):
        return value

    raw = value.strip().upper().replace(" ", "")
    if not raw:
        raise ValueError("MAX_UPLOAD_SIZE cannot be empty")

    # Longer suffixes first so "50MB" matches MB, not B
    multipliers: tuple[tuple[str, int], ...] = (
        ("GB", 1024**3),
        ("MB", 1024**2),
        ("KB", 1024),
        ("B", 1),
    )

    for suffix, multiplier in multipliers:
        if raw.endswith(suffix):
            number = raw[: -len(suffix)]
            try:
                return int(float(number) * multiplier)
            except ValueError as exc:
                raise ValueError(f"Invalid size value: {value}") from exc

    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"Invalid size value: {value}. Use an integer or a suffix like 50MB."
        ) from exc


class Settings(BaseSettings):
    """Runtime settings sourced from ``.env`` and process environment."""

    model_config = SettingsConfigDict(
        env_file=str(_project_root() / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Kept for compatibility with .env; auth uses app.core.constants.API_KEY
    api_key: str = Field(default="microfindev263", alias="API_KEY")
    port: int = Field(default=8000, alias="PORT")
    max_upload_size: str = Field(default="50MB", alias="MAX_UPLOAD_SIZE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Derived / path settings (not typically overridden via env)
    app_name: str = "Document & Image Service"
    app_version: str = "1.0.0"

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return level

    @property
    def max_upload_size_bytes(self) -> int:
        """Maximum allowed upload size in bytes."""
        return parse_size(self.max_upload_size)

    @property
    def base_dir(self) -> Path:
        """Project root directory."""
        return _project_root()

    @property
    def app_dir(self) -> Path:
        """Application package directory."""
        return self.base_dir / "app"

    @property
    def storage_dir(self) -> Path:
        """Root storage directory."""
        return self.app_dir / "storage"

    @property
    def documents_dir(self) -> Path:
        return self.storage_dir / "documents"

    @property
    def images_dir(self) -> Path:
        return self.storage_dir / "images"

    @property
    def optimized_dir(self) -> Path:
        return self.storage_dir / "optimized"

    @property
    def thumbnails_dir(self) -> Path:
        return self.storage_dir / "thumbnails"

    @property
    def logs_dir(self) -> Path:
        return self.base_dir / "logs"

    @property
    def log_file(self) -> Path:
        return self.logs_dir / "application.log"

    def ensure_directories(self) -> None:
        """Create storage and log directories if they do not exist."""
        for path in (
            self.documents_dir,
            self.images_dir,
            self.optimized_dir,
            self.thumbnails_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance for dependency injection."""
    settings = Settings()
    settings.ensure_directories()
    return settings
