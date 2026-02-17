"""
Authentication service for business logic.
"""
import logging
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_token, hash_password, verify_password
from app.models import Token, User

logger = logging.getLogger(__name__)


class AuthService:
    """Service for authentication operations."""

    @staticmethod
    async def register_user(
        db: AsyncSession,
        username: str,
        email: str,
        password: str,
    ) -> Tuple[User, Token]:
        """
        Register a new user.

        Args:
            db: Database session
            username: Username
            email: Email address
            password: Plain text password

        Returns:
            Tuple of (User, Token)

        Raises:
            ValueError: If username or email already exists
        """
        # Check if username exists
        stmt = select(User).where(User.username == username)
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            raise ValueError("Username already registered")

        # Check if email exists
        stmt = select(User).where(User.email == email)
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            raise ValueError("Email already registered")

        # Create user
        user = User(
            username=username,
            email=email,
            hashed_password=hash_password(password),
        )
        db.add(user)
        await db.flush()

        # Create token
        token = Token(
            key=generate_token(),
            user_id=user.id,
        )
        db.add(token)
        await db.flush()

        logger.info(f"User registered: {username}")
        return user, token

    @staticmethod
    async def authenticate_user(
        db: AsyncSession,
        username: str,
        password: str,
    ) -> Optional[Tuple[User, Token]]:
        """
        Authenticate a user.

        Args:
            db: Database session
            username: Username
            password: Plain text password

        Returns:
            Tuple of (User, Token) if successful, None otherwise
        """
        # Find user
        stmt = select(User).where(User.username == username)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            return None

        if not verify_password(password, user.hashed_password):
            return None

        if not user.is_active:
            return None

        # Get or create token
        stmt = select(Token).where(Token.user_id == user.id)
        result = await db.execute(stmt)
        token = result.scalar_one_or_none()

        if not token:
            token = Token(
                key=generate_token(),
                user_id=user.id,
            )
            db.add(token)
            await db.flush()

        logger.info(f"User authenticated: {username}")
        return user, token

    @staticmethod
    async def logout_user(db: AsyncSession, user_id: int) -> None:
        """
        Logout a user by deleting their tokens.

        Args:
            db: Database session
            user_id: User ID
        """
        stmt = select(Token).where(Token.user_id == user_id)
        result = await db.execute(stmt)
        tokens = result.scalars().all()

        for token in tokens:
            await db.delete(token)

        logger.info(f"User logged out: user_id={user_id}")

    @staticmethod
    async def change_password(
        db: AsyncSession,
        user: User,
        current_password: str,
        new_password: str,
    ) -> bool:
        """
        Change a user's password.

        Args:
            db: Database session
            user: User object
            current_password: Current password
            new_password: New password

        Returns:
            True if successful, False if current password is incorrect
        """
        if not verify_password(current_password, user.hashed_password):
            return False

        user.hashed_password = hash_password(new_password)
        db.add(user)
        await db.flush()

        logger.info(f"Password changed: {user.username}")
        return True
