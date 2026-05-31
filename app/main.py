"""
FastAPI application entry point.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.config import settings
from app.core.middleware import RateLimitMiddleware, RequestLoggingMiddleware
from app.database import close_redis

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(levelname)s %(asctime)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting Nakh FastAPI application...")

    # Create media directory
    media_path = settings.media_path
    media_path.mkdir(parents=True, exist_ok=True)
    (media_path / "uploads").mkdir(exist_ok=True)
    (media_path / "processed").mkdir(exist_ok=True)
    (media_path / "videos").mkdir(exist_ok=True)
    (media_path / "body_models").mkdir(exist_ok=True)
    (media_path / "chat" / "sessions").mkdir(parents=True, exist_ok=True)
    (media_path / "chat" / "preferences").mkdir(parents=True, exist_ok=True)

    # Create logs directory
    logs_path = Path("logs")
    logs_path.mkdir(exist_ok=True)

    # Initialize LLM for chatbot
    if settings.llm_enabled and settings.llm_model_path:
        try:
            from app.services.llm import llm_manager

            logger.info(f"Initializing LLM: {settings.llm_model_path}")
            llm_manager.initialize(
                model_path=settings.llm_model_path,
                model_type=settings.llm_model_type,
                device=settings.llm_device,
                load_in_8bit=settings.llm_load_in_8bit,
                load_in_4bit=settings.llm_load_in_4bit,
                ollama_base_url=settings.ollama_base_url,
            )
            logger.info("LLM initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize LLM: {e}. Chat will use fallback responses.")
    else:
        logger.info("LLM disabled or not configured. Chat will use fallback responses.")

    logger.info("Application started successfully")

    yield

    # Shutdown
    logger.info("Shutting down Nakh FastAPI application...")

    # Shutdown LLM
    if settings.llm_enabled:
        try:
            from app.services.llm import llm_manager
            llm_manager.shutdown()
        except Exception as e:
            logger.warning(f"Error shutting down LLM: {e}")

    try:
        await close_redis()
    except Exception as e:
        logger.warning(f"Error closing Redis (may not be in use): {e}")
    logger.info("Application shutdown complete")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    description="AI-powered tailoring platform for body measurement analysis",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# Add middleware
# In debug mode, allow any origin so local frontends on arbitrary ports work.
# In production, restrict to the origins listed in CORS_ORIGINS.
_cors_origins = ["*"] if settings.debug else settings.cors_origins_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if settings.rate_limit_enabled:
    app.add_middleware(RateLimitMiddleware)

if settings.debug:
    app.add_middleware(RequestLoggingMiddleware)

# Include API routers
app.include_router(api_router, prefix="/api/v1")

# Mount static files for media
media_path = settings.media_path
if media_path.exists():
    app.mount("/media", StaticFiles(directory=str(media_path)), name="media")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "status": "running",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=settings.debug,
    )
