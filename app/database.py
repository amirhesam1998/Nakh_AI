"""
Redis storage management.

Uses Redis for all data storage (users, tokens, uploads).
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import redis.asyncio as redis

from app.config import settings

# Redis client instance
_redis_client: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    """Get Redis client instance."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None


class RedisStorage:
    """Redis-based storage for application data."""

    # Key prefixes
    USER_PREFIX = "user:"
    TOKEN_PREFIX = "token:"
    UPLOAD_PREFIX = "upload:"
    USERNAME_INDEX = "username:"
    EMAIL_INDEX = "email:"
    USER_UPLOADS_PREFIX = "user_uploads:"

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    # ==================== User Operations ====================

    async def create_user(
        self,
        user_id: str,
        username: str,
        email: str,
        hashed_password: str,
    ) -> Dict[str, Any]:
        """Create a new user."""
        user_data = {
            "id": user_id,
            "username": username,
            "email": email,
            "hashed_password": hashed_password,
            "is_active": True,
            "created_at": datetime.utcnow().isoformat(),
        }

        # Store user data
        await self.redis.set(
            f"{self.USER_PREFIX}{user_id}",
            json.dumps(user_data),
        )

        # Create username -> user_id index
        await self.redis.set(f"{self.USERNAME_INDEX}{username.lower()}", user_id)

        # Create email -> user_id index
        await self.redis.set(f"{self.EMAIL_INDEX}{email.lower()}", user_id)

        return user_data

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID."""
        data = await self.redis.get(f"{self.USER_PREFIX}{user_id}")
        return json.loads(data) if data else None

    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username."""
        user_id = await self.redis.get(f"{self.USERNAME_INDEX}{username.lower()}")
        if not user_id:
            return None
        return await self.get_user_by_id(user_id)

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email."""
        user_id = await self.redis.get(f"{self.EMAIL_INDEX}{email.lower()}")
        if not user_id:
            return None
        return await self.get_user_by_id(user_id)

    async def update_user(self, user_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update user data."""
        user = await self.get_user_by_id(user_id)
        if not user:
            return None

        # Handle username change
        if "username" in updates and updates["username"] != user["username"]:
            await self.redis.delete(f"{self.USERNAME_INDEX}{user['username'].lower()}")
            await self.redis.set(f"{self.USERNAME_INDEX}{updates['username'].lower()}", user_id)

        # Handle email change
        if "email" in updates and updates["email"] != user["email"]:
            await self.redis.delete(f"{self.EMAIL_INDEX}{user['email'].lower()}")
            await self.redis.set(f"{self.EMAIL_INDEX}{updates['email'].lower()}", user_id)

        user.update(updates)
        await self.redis.set(f"{self.USER_PREFIX}{user_id}", json.dumps(user))
        return user

    # ==================== Token Operations ====================

    async def create_token(self, token_key: str, user_id: str) -> Dict[str, Any]:
        """Create an auth token."""
        token_data = {
            "key": token_key,
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
        }

        await self.redis.set(
            f"{self.TOKEN_PREFIX}{token_key}",
            json.dumps(token_data),
            ex=settings.token_expiry_seconds,
        )

        return token_data

    async def get_token(self, token_key: str) -> Optional[Dict[str, Any]]:
        """Get token data."""
        data = await self.redis.get(f"{self.TOKEN_PREFIX}{token_key}")
        return json.loads(data) if data else None

    async def delete_token(self, token_key: str) -> bool:
        """Delete a token."""
        result = await self.redis.delete(f"{self.TOKEN_PREFIX}{token_key}")
        return result > 0

    async def delete_user_tokens(self, user_id: str) -> int:
        """Delete all tokens for a user (scan and delete)."""
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor, match=f"{self.TOKEN_PREFIX}*", count=100)
            for key in keys:
                data = await self.redis.get(key)
                if data:
                    token_data = json.loads(data)
                    if token_data.get("user_id") == user_id:
                        await self.redis.delete(key)
                        deleted += 1
            if cursor == 0:
                break
        return deleted

    # ==================== Upload Operations ====================

    async def create_upload(
        self,
        upload_id: str,
        user_id: Optional[str],
        image1: str,
        image2: Optional[str] = None,
        image3: Optional[str] = None,
        height_cm: Optional[float] = None,
        weight_kg: Optional[float] = None,
        gender: str = "male",
    ) -> Dict[str, Any]:
        """Create an upload record."""
        upload_data = {
            "id": upload_id,
            "user_id": user_id,
            "image1": image1,
            "image2": image2,
            "image3": image3,
            "height_cm": height_cm,
            "weight_kg": weight_kg,
            "gender": gender,
            "uploaded_at": datetime.utcnow().isoformat(),
            "processed_at": None,
            "is_processed": False,
            "processing_results": None,
        }

        await self.redis.set(
            f"{self.UPLOAD_PREFIX}{upload_id}",
            json.dumps(upload_data),
            ex=settings.upload_expiry_seconds,
        )

        # Add to user's upload list
        if user_id:
            await self.redis.lpush(f"{self.USER_UPLOADS_PREFIX}{user_id}", upload_id)

        return upload_data

    async def get_upload(self, upload_id: str) -> Optional[Dict[str, Any]]:
        """Get upload by ID."""
        data = await self.redis.get(f"{self.UPLOAD_PREFIX}{upload_id}")
        return json.loads(data) if data else None

    async def update_upload(self, upload_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update upload data."""
        upload = await self.get_upload(upload_id)
        if not upload:
            return None

        upload.update(updates)

        # Preserve TTL when updating
        ttl = await self.redis.ttl(f"{self.UPLOAD_PREFIX}{upload_id}")
        if ttl > 0:
            await self.redis.set(
                f"{self.UPLOAD_PREFIX}{upload_id}",
                json.dumps(upload),
                ex=ttl,
            )
        else:
            await self.redis.set(
                f"{self.UPLOAD_PREFIX}{upload_id}",
                json.dumps(upload),
            )

        return upload

    async def delete_upload(self, upload_id: str) -> bool:
        """Delete an upload."""
        upload = await self.get_upload(upload_id)
        if not upload:
            return False

        # Remove from user's upload list
        if upload.get("user_id"):
            await self.redis.lrem(f"{self.USER_UPLOADS_PREFIX}{upload['user_id']}", 0, upload_id)

        result = await self.redis.delete(f"{self.UPLOAD_PREFIX}{upload_id}")
        return result > 0

    async def get_user_uploads(
        self,
        user_id: str,
        page: int = 1,
        size: int = 20,
    ) -> tuple[List[Dict[str, Any]], int]:
        """Get paginated uploads for a user."""
        # Get all upload IDs for user
        upload_ids = await self.redis.lrange(
            f"{self.USER_UPLOADS_PREFIX}{user_id}",
            0, -1,
        )

        total = len(upload_ids)

        # Paginate
        start = (page - 1) * size
        end = start + size
        page_ids = upload_ids[start:end]

        # Fetch upload data
        uploads = []
        for upload_id in page_ids:
            upload = await self.get_upload(upload_id)
            if upload:
                uploads.append(upload)

        return uploads, total


async def get_storage() -> RedisStorage:
    """Get storage instance."""
    redis_client = await get_redis()
    return RedisStorage(redis_client)
