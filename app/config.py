"""
Application configuration using Pydantic Settings.

All configuration is loaded from environment variables.
"""
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Nakh"
    debug: bool = True
    secret_key: str = "change-me-in-production"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_enabled: bool = False
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    celery_task_time_limit: int = 1800  # 30 minutes

    # CORS
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins as list."""
        return [origin.strip() for origin in self.cors_origins.split(",")]

    # Rate Limiting
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 30

    # File Upload
    max_upload_size_mb: int = 10
    media_root: str = "./media"

    @property
    def media_path(self) -> Path:
        """Get media root as Path object."""
        return Path(self.media_root)

    # Logging
    log_level: str = "INFO"

    # Token expiry (seconds) - default 7 days
    token_expiry_seconds: int = 7 * 24 * 60 * 60

    # Upload expiry (seconds) - default 24 hours
    upload_expiry_seconds: int = 24 * 60 * 60

    # Allowed image extensions and MIME types
    allowed_image_extensions: List[str] = [".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"]
    allowed_image_mime_types: List[str] = [
        "image/jpeg",
        "image/png",
        "image/heic",
        "image/heif",
        "image/webp",
    ]
    # Minimum image resolution (width or height)
    min_image_resolution: int = 480

    # LLM Configuration
    llm_enabled: bool = True
    llm_model_path: str = ""  # Path to model (local or HuggingFace hub)
    llm_model_type: str = "transformers"  # "transformers" or "gguf"
    llm_device: str = "auto"  # "auto", "cpu", "cuda"
    llm_max_tokens: int = 512
    llm_temperature: float = 0.7
    llm_load_in_8bit: bool = False  # Quantization for lower memory
    llm_load_in_4bit: bool = False  # More aggressive quantization

    # Ollama (local LLM server)
    ollama_base_url: str = "http://localhost:11434"

    # External Shop API (for product recommendations)
    # In Docker, set SHOP_API_URL to the Laravel service name (e.g. http://nakh-cms:80).
    shop_api_url: str = ""
    shop_api_key: str = ""

    # E-commerce auth proxy (validate Sanctum tokens against the Laravel CMS).
    # Leave empty to disable the auth proxy and treat tokens as opaque session IDs.
    # In Docker, set ECOMMERCE_AUTH_URL to the Laravel service name.
    ecommerce_auth_url: str = ""
    ecommerce_api_key: str = ""
    auth_cache_ttl_seconds: int = 300

    # Server bind (used when running `python -m app.main` directly)
    server_host: str = "0.0.0.0"
    server_port: int = 8000


# Create global settings instance
settings = Settings()
