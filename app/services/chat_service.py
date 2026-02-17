"""
Chat service - Main orchestrator for the chatbot.

Handles:
- Chat session management
- Message processing
- Context building
- LLM interaction
- Product recommendations
"""
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from app.database import get_redis
from app.config import settings
from app.schemas.chat import (
    ChatMessage,
    ChatSessionResponse,
    ChatHistoryResponse,
    UserPreferences,
    ProductRecommendation,
    MessageRole,
)
from app.services.llm import llm_manager
from app.services.context_builder import ContextBuilder
from app.services.product_service import product_service

logger = logging.getLogger(__name__)

# Redis key prefixes
CHAT_SESSION_PREFIX = "chat_session:"
CHAT_MESSAGES_PREFIX = "chat_messages:"
USER_PREFERENCES_PREFIX = "user_preferences:"

# Session TTL (7 days)
SESSION_TTL = 7 * 24 * 60 * 60


class ChatService:
    """
    Main chat service that orchestrates the chatbot functionality.
    """

    def __init__(self):
        self.context_builder = ContextBuilder(language="fa")

    async def create_session(
        self,
        user_id: str,
        include_measurements: bool = True,
        preferred_language: str = "fa",
    ) -> ChatSessionResponse:
        """
        Create a new chat session.

        Args:
            user_id: The user ID
            include_measurements: Whether to include measurements in context
            preferred_language: Language preference (fa/en)

        Returns:
            ChatSessionResponse with session info
        """
        session_id = str(uuid.uuid4())
        now = datetime.utcnow()

        session_data = {
            "session_id": session_id,
            "user_id": user_id,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "include_measurements": include_measurements,
            "preferred_language": preferred_language,
            "message_count": 0,
        }

        redis = await get_redis()
        await redis.setex(
            f"{CHAT_SESSION_PREFIX}{session_id}",
            SESSION_TTL,
            json.dumps(session_data)
        )

        # Add to user's sessions list
        await redis.lpush(f"user_chat_sessions:{user_id}", session_id)

        logger.info(f"Created chat session {session_id} for user {user_id}")

        return ChatSessionResponse(
            session_id=session_id,
            user_id=user_id,
            created_at=now,
            message_count=0,
            include_measurements=include_measurements,
            preferred_language=preferred_language,
        )

    async def get_session(self, session_id: str) -> Optional[ChatSessionResponse]:
        """Get a chat session by ID."""
        redis = await get_redis()
        data = await redis.get(f"{CHAT_SESSION_PREFIX}{session_id}")

        if not data:
            return None

        session_data = json.loads(data)
        return ChatSessionResponse(
            session_id=session_data["session_id"],
            user_id=session_data["user_id"],
            created_at=datetime.fromisoformat(session_data["created_at"]),
            message_count=session_data["message_count"],
            include_measurements=session_data["include_measurements"],
            preferred_language=session_data["preferred_language"],
        )

    async def get_or_create_session(
        self,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> ChatSessionResponse:
        """
        Get existing session or create a new one.

        Args:
            user_id: The user ID
            session_id: Optional existing session ID

        Returns:
            ChatSessionResponse
        """
        if session_id:
            session = await self.get_session(session_id)
            if session and session.user_id == user_id:
                return session

        # Get user's latest session or create new one
        redis = await get_redis()
        sessions = await redis.lrange(f"user_chat_sessions:{user_id}", 0, 0)

        if sessions:
            latest_session_id = sessions[0]
            session = await self.get_session(latest_session_id)
            if session:
                return session

        # Create new session
        return await self.create_session(user_id)

    async def delete_session(self, session_id: str, user_id: str) -> bool:
        """Delete a chat session and its messages."""
        redis = await get_redis()

        # Verify ownership
        session = await self.get_session(session_id)
        if not session or session.user_id != user_id:
            return False

        # Delete session and messages
        await redis.delete(f"{CHAT_SESSION_PREFIX}{session_id}")
        await redis.delete(f"{CHAT_MESSAGES_PREFIX}{session_id}")
        await redis.lrem(f"user_chat_sessions:{user_id}", 0, session_id)

        logger.info(f"Deleted chat session {session_id}")
        return True

    async def send_message(
        self,
        user_id: str,
        message: str,
        session_id: Optional[str] = None,
        measurements: Optional[dict] = None,
        preferences: Optional[UserPreferences] = None,
    ) -> tuple[ChatMessage, ChatMessage, list[ProductRecommendation]]:
        """
        Send a message and get a response.

        Args:
            user_id: The user ID
            message: The user's message
            session_id: Optional session ID
            measurements: User's body measurements
            preferences: User's preferences

        Returns:
            Tuple of (user_message, assistant_message, recommendations)
        """
        # Get or create session
        session = await self.get_or_create_session(user_id, session_id)

        # Update context builder language
        self.context_builder.language = session.preferred_language

        # Create user message
        user_msg = ChatMessage(
            role=MessageRole.USER,
            content=message,
            timestamp=datetime.utcnow()
        )

        # Store user message
        await self._store_message(session.session_id, user_msg)

        # Get chat history
        history = await self._get_messages(session.session_id, limit=10)

        # Build system prompt with context
        system_prompt = self.context_builder.build_system_prompt(
            measurements=measurements if session.include_measurements else None,
            preferences=preferences,
            include_product_context=True
        )

        # Format messages for LLM
        chat_messages = self.context_builder.format_chat_history(history)

        # Generate response
        assistant_text = await self._generate_response(
            chat_messages,
            system_prompt,
            session.preferred_language
        )

        # Create assistant message
        assistant_msg = ChatMessage(
            role=MessageRole.ASSISTANT,
            content=assistant_text,
            timestamp=datetime.utcnow()
        )

        # Store assistant message
        await self._store_message(session.session_id, assistant_msg)

        # Update session
        await self._update_session_count(session.session_id)

        # Check if we should recommend products
        recommendations = []
        if self._should_recommend_products(message, assistant_text):
            recommendations = await product_service.get_recommendations(
                measurements=measurements,
                preferences=preferences,
                conversation_context=f"{message}\n{assistant_text}",
                limit=3
            )

        return user_msg, assistant_msg, recommendations

    async def _generate_response(
        self,
        messages: list[dict],
        system_prompt: str,
        language: str
    ) -> str:
        """Generate a response from the LLM."""
        if not llm_manager.is_ready:
            # Fallback response when LLM is not available
            if language == "fa":
                return (
                    "متأسفانه در حال حاضر امکان پردازش پیام شما وجود ندارد. "
                    "لطفاً کمی صبر کنید یا دوباره تلاش کنید."
                )
            else:
                return (
                    "Sorry, I'm unable to process your message at the moment. "
                    "Please wait a moment or try again."
                )

        try:
            response = llm_manager.chat(
                messages=messages,
                system_prompt=system_prompt,
                max_new_tokens=512,
                temperature=0.7,
            )
            return response.text

        except Exception as e:
            logger.error(f"LLM generation error: {e}")
            if language == "fa":
                return "متأسفم، مشکلی در پردازش پیام شما پیش آمد. لطفاً دوباره تلاش کنید."
            else:
                return "Sorry, there was an error processing your message. Please try again."

    def _should_recommend_products(self, user_message: str, assistant_response: str) -> bool:
        """
        Determine if we should include product recommendations.

        Checks for keywords indicating product interest.
        """
        keywords_fa = [
            "پیشنهاد", "محصول", "خرید", "لباس", "پارچه",
            "کت", "شلوار", "پیراهن", "چه بخرم", "چی بپوشم",
            "سفارش", "قیمت", "فروشگاه"
        ]
        keywords_en = [
            "recommend", "product", "buy", "clothes", "fabric",
            "jacket", "pants", "shirt", "what to wear", "order",
            "price", "shop", "suggest"
        ]

        combined_text = f"{user_message} {assistant_response}".lower()

        for keyword in keywords_fa + keywords_en:
            if keyword in combined_text:
                return True

        return False

    async def _store_message(self, session_id: str, message: ChatMessage) -> None:
        """Store a message in Redis."""
        redis = await get_redis()
        message_data = {
            "role": message.role.value,
            "content": message.content,
            "timestamp": message.timestamp.isoformat()
        }
        await redis.rpush(
            f"{CHAT_MESSAGES_PREFIX}{session_id}",
            json.dumps(message_data, ensure_ascii=False)
        )
        # Set TTL on messages
        await redis.expire(f"{CHAT_MESSAGES_PREFIX}{session_id}", SESSION_TTL)

    async def _get_messages(
        self,
        session_id: str,
        limit: int = 50
    ) -> list[ChatMessage]:
        """Get messages from a session."""
        redis = await get_redis()
        messages_data = await redis.lrange(
            f"{CHAT_MESSAGES_PREFIX}{session_id}",
            -limit, -1
        )

        messages = []
        for data in messages_data:
            msg_dict = json.loads(data)
            messages.append(ChatMessage(
                role=MessageRole(msg_dict["role"]),
                content=msg_dict["content"],
                timestamp=datetime.fromisoformat(msg_dict["timestamp"])
            ))

        return messages

    async def _update_session_count(self, session_id: str) -> None:
        """Update the message count for a session."""
        redis = await get_redis()
        data = await redis.get(f"{CHAT_SESSION_PREFIX}{session_id}")

        if data:
            session_data = json.loads(data)
            session_data["message_count"] = session_data.get("message_count", 0) + 2
            session_data["updated_at"] = datetime.utcnow().isoformat()

            await redis.setex(
                f"{CHAT_SESSION_PREFIX}{session_id}",
                SESSION_TTL,
                json.dumps(session_data)
            )

    async def get_chat_history(
        self,
        session_id: str,
        user_id: str,
    ) -> Optional[ChatHistoryResponse]:
        """
        Get chat history for a session.

        Args:
            session_id: The session ID
            user_id: The user ID (for verification)

        Returns:
            ChatHistoryResponse or None
        """
        session = await self.get_session(session_id)
        if not session or session.user_id != user_id:
            return None

        messages = await self._get_messages(session_id, limit=100)

        redis = await get_redis()
        data = await redis.get(f"{CHAT_SESSION_PREFIX}{session_id}")
        session_data = json.loads(data)

        return ChatHistoryResponse(
            session_id=session_id,
            messages=messages,
            created_at=datetime.fromisoformat(session_data["created_at"]),
            updated_at=datetime.fromisoformat(session_data["updated_at"]),
        )

    async def get_user_preferences(self, user_id: str) -> Optional[UserPreferences]:
        """Get user preferences from storage."""
        redis = await get_redis()
        data = await redis.get(f"{USER_PREFERENCES_PREFIX}{user_id}")

        if not data:
            return None

        pref_data = json.loads(data)
        return UserPreferences(**pref_data)

    async def update_user_preferences(
        self,
        user_id: str,
        preferences: UserPreferences
    ) -> UserPreferences:
        """Update user preferences."""
        redis = await get_redis()
        await redis.set(
            f"{USER_PREFERENCES_PREFIX}{user_id}",
            json.dumps(preferences.model_dump(), ensure_ascii=False)
        )
        return preferences

    async def clear_chat_history(self, session_id: str, user_id: str) -> bool:
        """Clear chat history for a session."""
        session = await self.get_session(session_id)
        if not session or session.user_id != user_id:
            return False

        redis = await get_redis()
        await redis.delete(f"{CHAT_MESSAGES_PREFIX}{session_id}")

        # Reset message count
        data = await redis.get(f"{CHAT_SESSION_PREFIX}{session_id}")
        if data:
            session_data = json.loads(data)
            session_data["message_count"] = 0
            await redis.setex(
                f"{CHAT_SESSION_PREFIX}{session_id}",
                SESSION_TTL,
                json.dumps(session_data)
            )

        return True


# Global instance
chat_service = ChatService()
