"""
Application configuration using Pydantic Settings.

All configuration is loaded from environment variables.
"""
import logging
from pathlib import Path
from typing import List

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_DEFAULT_SECRET_KEY = "change-me-in-production"


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

    # When False (production default), the recommendation pipeline NEVER returns
    # fabricated mock products to a real user — it surfaces an "unavailable"
    # state instead.  Set True only for local development / tests.
    allow_mock_products: bool = False

    # ── LLM concurrency / caching ──
    # Max number of concurrent LLM generations (protects the event loop thread
    # pool and the Ollama server from overload under traffic spikes).
    llm_max_concurrency: int = 2
    # How long Ollama keeps the model warm in memory between calls. A stable
    # system prompt + warm model lets Ollama reuse the cached prompt prefix.
    llm_keep_alive: str = "30m"

    # ── PARE processing queue ──
    # Number of worker threads dedicated to (GPU-heavy) PARE processing.
    # Keep at 1 unless you have multiple GPUs / plenty of VRAM.
    pare_max_workers: int = 1
    # Reject new processing jobs when this many are already queued/running.
    pare_max_queue_depth: int = 20

    # ── Semantic recommendation scoring (optional) ──
    # When True, candidate products are re-ranked using vector similarity
    # between the user's preference text and each product (via Ollama
    # embeddings). Falls back to token scoring if the embedder is unreachable.
    embedding_enabled: bool = False
    embedding_model: str = "nomic-embed-text"
    # Blend weight: final = (1-w)*token_score + w*semantic_score
    embedding_blend_weight: float = 0.4

    # ── Observability ──
    metrics_enabled: bool = True
    # Append-only behavioural event log (recommendation impressions, clicks,
    # purchases, fit feedback). Seeds the future ranking / accuracy models.
    event_log_enabled: bool = True

    # E-commerce auth proxy (validate Sanctum tokens against the Laravel CMS).
    # Leave empty to disable the auth proxy and treat tokens as opaque session IDs.
    # In Docker, set ECOMMERCE_AUTH_URL to the Laravel service name.
    ecommerce_auth_url: str = ""
    ecommerce_api_key: str = ""
    auth_cache_ttl_seconds: int = 300

    # Meilisearch — attribute-based product search.
    # When set, product recommendations query Meilisearch instead of CMS
    # for attribute filtering (occasion, season, color, style, etc.).
    meilisearch_url: str = ""
    meilisearch_key: str = ""

    # Internal Laravel API — shared secret for FastAPI ↔ Laravel communication.
    # When set, chat sessions and measurements are persisted via Laravel MySQL
    # instead of local JSON files / Redis.
    internal_api_url: str = ""
    internal_api_key: str = ""

    # Server bind (used when running `python -m app.main` directly)
    server_host: str = "0.0.0.0"
    server_port: int = 8000

    @model_validator(mode="after")
    def _validate_production_safety(self) -> "Settings":
        """Fail fast on insecure production configuration.

        When ``debug`` is False the app is assumed to be running in a
        production-like environment, where shipping the placeholder secret key
        is a real security hole. We refuse to start rather than silently sign
        tokens with a publicly-known key.
        """
        if not self.debug and self.secret_key == _DEFAULT_SECRET_KEY:
            raise ValueError(
                "SECRET_KEY is still the default placeholder while DEBUG=false. "
                "Set a strong, unique SECRET_KEY in the environment before "
                "running in production."
            )
        if self.debug and self.secret_key == _DEFAULT_SECRET_KEY:
            logger.warning(
                "Using the default SECRET_KEY — fine for local dev, but MUST be "
                "overridden in production (set DEBUG=false to enforce)."
            )
        return self


# Create global settings instance
settings = Settings()
