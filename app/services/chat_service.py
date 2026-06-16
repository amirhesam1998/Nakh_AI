"""
Chat service - Main orchestrator for the chatbot.

Handles:
- Chat session management
- Message processing
- Context building
- LLM interaction
- Product recommendations

Storage: JSON files under media/chat/ (no Redis required).
"""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

# Per-message cap. Anything longer is truncated before storage / prompting.
_MAX_USER_MESSAGE_CHARS = 2000

# Drop chat-template delimiter sequences from user input so a hostile user
# cannot pretend to be the system role or end the turn early.
_PROMPT_DELIMITER_RE = re.compile(r"<\|[^|>]{0,40}\|>")


def _sanitize_user_message(text: str) -> str:
    """Cap length and strip chat-template control tokens from user input."""
    if not isinstance(text, str):
        text = str(text or "")
    text = _PROMPT_DELIMITER_RE.sub("", text)
    text = text.replace("```", "´´´")
    if len(text) > _MAX_USER_MESSAGE_CHARS:
        text = text[: _MAX_USER_MESSAGE_CHARS - 1] + "…"
    return text

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

# Session TTL (7 days) — not enforced at file level, but kept for reference
SESSION_TTL = 7 * 24 * 60 * 60

# ---------- JSON file helpers ----------

_SESSIONS_DIR: Path = settings.media_path / "chat" / "sessions"
_PREFS_DIR: Path = settings.media_path / "chat" / "preferences"


def _ensure_dirs() -> None:
    _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    _PREFS_DIR.mkdir(parents=True, exist_ok=True)


def _session_path(session_id: str) -> Path:
    return _SESSIONS_DIR / f"{session_id}.json"


def _user_index_path(user_id: str) -> Path:
    return _SESSIONS_DIR / f"user_{user_id}.json"


def _prefs_path(user_id: str) -> Path:
    return _PREFS_DIR / f"{user_id}.json"


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically via .tmp + replace."""
    _ensure_dirs()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_json_list(path: Path) -> list:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


# ---- Internal API backend (MySQL via Laravel) ----

class _InternalAPIBackend:
    """Stores chat sessions and messages via Laravel internal API.

    Used when ``INTERNAL_API_URL`` is set.  Falls back silently to
    JSON files if an API call fails.
    """

    def __init__(self, base_url: str, api_key: str):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "X-Internal-Key": self._api_key,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def create_session(self, user_id: str, **kwargs) -> Optional[dict]:
        try:
            client = await self._get_client()
            resp = await client.post(
                f"/api/internal/users/{user_id}/chat-sessions",
                json=kwargs,
            )
            resp.raise_for_status()
            return resp.json().get("data") or resp.json()
        except Exception as e:
            logger.warning("Internal API create_session failed: %s", e)
            return None

    async def get_session(self, session_uuid: str) -> Optional[dict]:
        try:
            client = await self._get_client()
            resp = await client.get(f"/api/internal/chat-sessions/{session_uuid}")
            resp.raise_for_status()
            return resp.json().get("data") or resp.json()
        except Exception as e:
            logger.debug("Internal API get_session failed: %s", e)
            return None

    async def list_sessions(self, user_id: str) -> list[dict]:
        try:
            client = await self._get_client()
            resp = await client.get(f"/api/internal/users/{user_id}/chat-sessions")
            resp.raise_for_status()
            data = resp.json()
            return data.get("data") if isinstance(data.get("data"), list) else []
        except Exception as e:
            logger.debug("Internal API list_sessions failed: %s", e)
            return []

    async def append_message(self, session_uuid: str, role: str, content: str) -> bool:
        try:
            client = await self._get_client()
            resp = await client.post(
                f"/api/internal/chat-sessions/{session_uuid}/messages",
                json={"role": role, "content": content},
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.warning("Internal API append_message failed: %s", e)
            return False

    async def save_measurements(self, user_id: str, measurements: dict) -> bool:
        try:
            client = await self._get_client()
            resp = await client.post(
                f"/api/internal/users/{user_id}/measurements",
                json=measurements,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.warning("Internal API save_measurements failed: %s", e)
            return False


# ------------------------------------------------------------------


class ChatService:
    """
    Main chat service that orchestrates the chatbot functionality.

    When ``INTERNAL_API_URL`` is configured, sessions and messages are
    stored via the Laravel internal API (MySQL).  Otherwise, JSON files
    under ``media/chat/`` are used as the storage backend.
    """

    def __init__(self):
        self.context_builder = ContextBuilder(language="fa")
        internal_url = getattr(settings, "internal_api_url", "") or ""
        internal_key = getattr(settings, "internal_api_key", "") or ""
        self._api: Optional[_InternalAPIBackend] = (
            _InternalAPIBackend(internal_url, internal_key) if internal_url else None
        )

    # ---- Session management (JSON-backed) ----

    async def create_session(
        self,
        user_id: str,
        include_measurements: bool = True,
        preferred_language: str = "fa",
    ) -> ChatSessionResponse:
        session_id = str(uuid.uuid4())
        now = datetime.utcnow()

        # Try internal API first
        if self._api:
            api_data = await self._api.create_session(
                user_id,
                uuid=session_id,
                include_measurements=include_measurements,
                preferred_language=preferred_language,
            )
            if api_data:
                logger.info("Created chat session %s via internal API", session_id)
                return ChatSessionResponse(
                    session_id=api_data.get("uuid", session_id),
                    user_id=user_id,
                    created_at=now,
                    message_count=0,
                    include_measurements=include_measurements,
                    preferred_language=preferred_language,
                )

        # Fallback: JSON file
        session_data = {
            "session_id": session_id,
            "user_id": user_id,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "include_measurements": include_measurements,
            "preferred_language": preferred_language,
            "message_count": 0,
            "messages": [],
        }

        _atomic_write(_session_path(session_id), session_data)

        # Update user index
        idx = _read_json_list(_user_index_path(user_id))
        idx.insert(0, session_id)
        _atomic_write(_user_index_path(user_id), idx)

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
        # Try internal API first
        if self._api:
            api_data = await self._api.get_session(session_id)
            if api_data:
                return ChatSessionResponse(
                    session_id=api_data.get("uuid", session_id),
                    user_id=str(api_data.get("user_id", "")),
                    created_at=datetime.fromisoformat(api_data["created_at"]) if "created_at" in api_data else datetime.utcnow(),
                    message_count=api_data.get("message_count", 0),
                    include_measurements=api_data.get("include_measurements", True),
                    preferred_language=api_data.get("preferred_language", "fa"),
                )

        # Fallback: JSON file
        data = _read_json(_session_path(session_id))
        if not data:
            return None
        return ChatSessionResponse(
            session_id=data["session_id"],
            user_id=data["user_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            message_count=data.get("message_count", 0),
            include_measurements=data.get("include_measurements", True),
            preferred_language=data.get("preferred_language", "fa"),
        )

    async def get_or_create_session(
        self,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> ChatSessionResponse:
        if session_id:
            session = await self.get_session(session_id)
            if session and session.user_id == user_id:
                return session

        idx = _read_json_list(_user_index_path(user_id))
        for sid in idx:
            session = await self.get_session(sid)
            if session:
                return session

        return await self.create_session(user_id)

    async def delete_session(self, session_id: str, user_id: str) -> bool:
        session = await self.get_session(session_id)
        if not session or session.user_id != user_id:
            return False

        path = _session_path(session_id)
        if path.exists():
            path.unlink()

        # Remove from user index
        idx = _read_json_list(_user_index_path(user_id))
        idx = [s for s in idx if s != session_id]
        _atomic_write(_user_index_path(user_id), idx)

        logger.info(f"Deleted chat session {session_id}")
        return True

    # ---- Messaging ----

    async def send_message(
        self,
        user_id: str,
        message: str,
        session_id: Optional[str] = None,
        measurements: Optional[dict] = None,
        preferences: Optional[UserPreferences] = None,
    ) -> tuple[ChatMessage, ChatMessage, list[ProductRecommendation]]:
        session = await self.get_or_create_session(user_id, session_id)

        self.context_builder.language = session.preferred_language

        safe_message = _sanitize_user_message(message)

        user_msg = ChatMessage(
            role=MessageRole.USER,
            content=safe_message,
            timestamp=datetime.utcnow(),
        )
        await self._store_message(session.session_id, user_msg)

        history = await self._get_messages(session.session_id, limit=10)

        system_prompt = self.context_builder.build_system_prompt(
            measurements=measurements if session.include_measurements else None,
            preferences=preferences,
            include_product_context=True,
        )
        chat_messages = self.context_builder.format_chat_history(history)

        assistant_text = await self._generate_response(
            chat_messages, system_prompt, session.preferred_language
        )

        assistant_msg = ChatMessage(
            role=MessageRole.ASSISTANT,
            content=assistant_text,
            timestamp=datetime.utcnow(),
        )
        await self._store_message(session.session_id, assistant_msg)
        await self._update_session_count(session.session_id)

        recommendations = []
        if self._should_recommend_products(safe_message, assistant_text):
            recommendations = await product_service.get_recommendations(
                measurements=measurements,
                preferences=preferences,
                conversation_context=f"{safe_message}\n{assistant_text}",
                limit=3,
            )

        return user_msg, assistant_msg, recommendations

    async def stream_message(
        self,
        user_id: str,
        message: str,
        session_id: Optional[str] = None,
        measurements: Optional[dict] = None,
        preferences: Optional[UserPreferences] = None,
    ):
        """Stream an assistant reply token-by-token (async generator of str).

        Persists the user message before streaming and the full assistant
        message after the stream completes. Yields a leading marker dict via
        the first item containing the session id, then plain text deltas.
        """
        from app.services.concurrency import llm_slot
        from app.services.metrics import metrics
        from starlette.concurrency import iterate_in_threadpool

        session = await self.get_or_create_session(user_id, session_id)
        self.context_builder.language = session.preferred_language

        safe_message = _sanitize_user_message(message)
        user_msg = ChatMessage(
            role=MessageRole.USER, content=safe_message, timestamp=datetime.utcnow(),
        )
        await self._store_message(session.session_id, user_msg)

        history = await self._get_messages(session.session_id, limit=10)
        system_prompt = self.context_builder.build_system_prompt(
            measurements=measurements if session.include_measurements else None,
            preferences=preferences,
            include_product_context=True,
        )
        chat_messages = self.context_builder.format_chat_history(history)

        # First item: session id so the client can correlate.
        yield {"session_id": session.session_id}

        full_text = ""
        if llm_manager.is_ready and llm_manager.supports_streaming:
            try:
                async with llm_slot("chat"):
                    with metrics.timer("chat.llm_seconds"):
                        sync_gen = llm_manager.chat_stream(
                            messages=chat_messages,
                            system_prompt=system_prompt,
                            max_new_tokens=512,
                            temperature=0.7,
                        )
                        async for delta in iterate_in_threadpool(sync_gen):
                            full_text += delta
                            yield delta
            except Exception as e:
                logger.error("Chat streaming error: %s", e)
        if not full_text:
            # Fallback (no LLM / streaming unsupported): non-streamed reply.
            full_text = await self._generate_response(
                chat_messages, system_prompt, session.preferred_language
            )
            yield full_text

        assistant_msg = ChatMessage(
            role=MessageRole.ASSISTANT, content=full_text, timestamp=datetime.utcnow(),
        )
        await self._store_message(session.session_id, assistant_msg)
        await self._update_session_count(session.session_id)

    async def _generate_response(
        self, messages: list[dict], system_prompt: str, language: str
    ) -> str:
        if not llm_manager.is_ready:
            if language == "fa":
                return (
                    "متأسفانه در حال حاضر امکان پردازش پیام شما وجود ندارد. "
                    "لطفاً کمی صبر کنید یا دوباره تلاش کنید."
                )
            return (
                "Sorry, I'm unable to process your message at the moment. "
                "Please wait a moment or try again."
            )

        try:
            # llm_manager.chat() is synchronous (blocking httpx to Ollama).
            # Run in thread + bound by the shared concurrency semaphore so a
            # spike of chat traffic can't exhaust the event-loop thread pool.
            from app.services.concurrency import llm_slot
            from app.services.metrics import metrics

            async with llm_slot("chat"):
                with metrics.timer("chat.llm_seconds"):
                    response = await asyncio.to_thread(
                        llm_manager.chat,
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
            return "Sorry, there was an error processing your message. Please try again."

    def _should_recommend_products(self, user_message: str, assistant_response: str) -> bool:
        keywords_fa = [
            "پیشنهاد", "محصول", "خرید", "لباس", "پارچه",
            "کت", "شلوار", "پیراهن", "چه بخرم", "چی بپوشم",
            "سفارش", "قیمت", "فروشگاه",
        ]
        keywords_en = [
            "recommend", "product", "buy", "clothes", "fabric",
            "jacket", "pants", "shirt", "what to wear", "order",
            "price", "shop", "suggest",
        ]
        combined = f"{user_message} {assistant_response}".lower()
        return any(kw in combined for kw in keywords_fa + keywords_en)

    # ---- JSON-backed message storage ----

    async def _store_message(self, session_id: str, message: ChatMessage) -> None:
        # Try internal API first
        if self._api:
            ok = await self._api.append_message(session_id, message.role.value, message.content)
            if ok:
                return

        # Fallback: JSON file
        path = _session_path(session_id)
        data = _read_json(path) or {}
        messages = data.get("messages", [])
        messages.append({
            "role": message.role.value,
            "content": message.content,
            "timestamp": message.timestamp.isoformat(),
        })
        data["messages"] = messages
        _atomic_write(path, data)

    async def _get_messages(self, session_id: str, limit: int = 50) -> list[ChatMessage]:
        data = _read_json(_session_path(session_id))
        if not data:
            return []
        raw = data.get("messages", [])[-limit:]
        return [
            ChatMessage(
                role=MessageRole(m["role"]),
                content=m["content"],
                timestamp=datetime.fromisoformat(m["timestamp"]),
            )
            for m in raw
        ]

    async def _update_session_count(self, session_id: str) -> None:
        path = _session_path(session_id)
        data = _read_json(path)
        if data:
            data["message_count"] = data.get("message_count", 0) + 2
            data["updated_at"] = datetime.utcnow().isoformat()
            _atomic_write(path, data)

    # ---- History ----

    async def get_chat_history(
        self, session_id: str, user_id: str
    ) -> Optional[ChatHistoryResponse]:
        session = await self.get_session(session_id)
        if not session or session.user_id != user_id:
            return None

        messages = await self._get_messages(session_id, limit=100)
        data = _read_json(_session_path(session_id)) or {}

        return ChatHistoryResponse(
            session_id=session_id,
            messages=messages,
            created_at=datetime.fromisoformat(data.get("created_at", datetime.utcnow().isoformat())),
            updated_at=datetime.fromisoformat(data.get("updated_at", datetime.utcnow().isoformat())),
        )

    # ---- Preferences (JSON-backed) ----

    async def get_user_preferences(self, user_id: str) -> Optional[UserPreferences]:
        data = _read_json(_prefs_path(user_id))
        if not data:
            return None
        return UserPreferences(**data)

    async def update_user_preferences(
        self, user_id: str, preferences: UserPreferences
    ) -> UserPreferences:
        _atomic_write(_prefs_path(user_id), preferences.model_dump())
        return preferences

    async def clear_chat_history(self, session_id: str, user_id: str) -> bool:
        session = await self.get_session(session_id)
        if not session or session.user_id != user_id:
            return False

        path = _session_path(session_id)
        data = _read_json(path)
        if data:
            data["messages"] = []
            data["message_count"] = 0
            _atomic_write(path, data)
        return True


# Global instance
chat_service = ChatService()
