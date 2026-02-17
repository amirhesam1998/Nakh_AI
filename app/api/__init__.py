"""
API routers for the Nakh application.
"""
from fastapi import APIRouter

from app.api import auth, users, uploads, health, chat

# Create main API router
api_router = APIRouter()

# Include sub-routers
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["Uploads"])
api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(chat.router, tags=["Chat"])
