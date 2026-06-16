"""
Chat API endpoints.

Provides endpoints for:
- Sending messages to the chatbot
- Managing chat sessions
- Managing user preferences
- Getting chat history
"""
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.config import settings
from app.core.dependencies import get_current_active_user
from app.schemas.chat import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
    ChatHistoryResponse,
    UserPreferences,
    UserPreferencesUpdate,
)
from app.services.chat_service import chat_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

METADATA_DIR = settings.media_path / "metadata"


@router.post("/sessions", response_model=ChatSessionResponse)
async def create_chat_session(
    session_config: ChatSessionCreate,
    current_user: dict = Depends(get_current_active_user),
):
    """Create a new chat session."""
    session = await chat_service.create_session(
        user_id=current_user["id"],
        include_measurements=session_config.include_measurements,
        preferred_language=session_config.preferred_language,
    )
    return session


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_chat_sessions(
    limit: int = 10,
    current_user: dict = Depends(get_current_active_user),
):
    """List user's chat sessions."""
    from app.services.chat_service import _read_json_list, _user_index_path

    idx = _read_json_list(_user_index_path(current_user["id"]))
    sessions = []
    for sid in idx[:limit]:
        session = await chat_service.get_session(sid)
        if session:
            sessions.append(session)
    return sessions


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_chat_session(
    session_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Get a specific chat session."""
    session = await chat_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
    if session.user_id != current_user["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return session


@router.delete("/sessions/{session_id}")
async def delete_chat_session(
    session_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Delete a chat session and its history."""
    success = await chat_service.delete_session(session_id, current_user["id"])
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found or access denied",
        )
    return {"message": "Session deleted successfully"}


@router.post("/message", response_model=ChatMessageResponse)
async def send_message(
    request: ChatMessageRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Send a message to the chatbot and receive a response."""
    measurements = _get_user_measurements(current_user["id"])
    preferences = await chat_service.get_user_preferences(current_user["id"])

    user_msg, assistant_msg, recommendations = await chat_service.send_message(
        user_id=current_user["id"],
        message=request.message,
        session_id=request.session_id,
        measurements=measurements,
        preferences=preferences,
    )

    session = await chat_service.get_or_create_session(
        current_user["id"], request.session_id
    )

    return ChatMessageResponse(
        session_id=session.session_id,
        user_message=user_msg,
        assistant_message=assistant_msg,
        recommended_products=recommendations,
    )


@router.post("/message/stream")
async def stream_message(
    request: ChatMessageRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """Stream a chatbot reply via Server-Sent Events (live typing UX).

    Emits `event: meta` (session id) once, then `event: token` deltas, then
    `event: done`.
    """
    measurements = _get_user_measurements(current_user["id"])
    preferences = await chat_service.get_user_preferences(current_user["id"])

    async def event_gen():
        try:
            agen = chat_service.stream_message(
                user_id=current_user["id"],
                message=request.message,
                session_id=request.session_id,
                measurements=measurements,
                preferences=preferences,
            )
            async for item in agen:
                if isinstance(item, dict):  # leading session marker
                    yield f"event: meta\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                else:
                    yield f"event: token\ndata: {json.dumps({'text': item}, ensure_ascii=False)}\n\n"
            yield "event: done\ndata: {}\n\n"
        except Exception as e:
            logger.error("Chat stream error: %s", e)
            yield f"event: error\ndata: {json.dumps({'message': 'stream_failed'})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Get chat history for a session."""
    history = await chat_service.get_chat_history(session_id, current_user["id"])
    if not history:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found or access denied",
        )
    return history


@router.delete("/history/{session_id}")
async def clear_chat_history(
    session_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """Clear chat history for a session (keeps the session)."""
    success = await chat_service.clear_chat_history(session_id, current_user["id"])
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found or access denied",
        )
    return {"message": "Chat history cleared successfully"}


@router.get("/preferences", response_model=Optional[UserPreferences])
async def get_preferences(
    current_user: dict = Depends(get_current_active_user),
):
    """Get user's clothing preferences."""
    return await chat_service.get_user_preferences(current_user["id"])


@router.put("/preferences", response_model=UserPreferences)
async def update_preferences(
    preferences: UserPreferencesUpdate,
    current_user: dict = Depends(get_current_active_user),
):
    """Update user's clothing preferences."""
    existing = await chat_service.get_user_preferences(current_user["id"])

    if existing:
        updated_data = existing.model_dump()
        update_dict = preferences.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            if value is not None:
                if key == "budget_min" and "budget_max" in update_dict:
                    updated_data["budget_range"] = (
                        update_dict.get("budget_min", 0),
                        update_dict.get("budget_max", float("inf")),
                    )
                elif key not in ["budget_min", "budget_max"]:
                    updated_data[key] = value
        new_preferences = UserPreferences(**updated_data)
    else:
        pref_dict = preferences.model_dump(exclude_unset=True)
        if "budget_min" in pref_dict or "budget_max" in pref_dict:
            pref_dict["budget_range"] = (
                pref_dict.pop("budget_min", 0),
                pref_dict.pop("budget_max", float("inf")),
            )
        new_preferences = UserPreferences(**pref_dict)

    return await chat_service.update_user_preferences(current_user["id"], new_preferences)


@router.delete("/preferences")
async def delete_preferences(
    current_user: dict = Depends(get_current_active_user),
):
    """Delete user's clothing preferences."""
    from app.services.chat_service import _prefs_path

    path = _prefs_path(current_user["id"])
    if path.exists():
        path.unlink()
    return {"message": "Preferences deleted successfully"}


# ---------- helpers ----------


def _get_user_measurements(user_id: str) -> Optional[dict]:
    """
    Get user's latest measurements via the indexed upload store (no full scan).
    """
    from app.services import upload_store

    # Newest-first, completed uploads only.
    candidates = [
        u for u in upload_store.list_user_metadata(user_id)
        if u.get("processing_status") == "completed" or u.get("is_processed")
    ]

    for upload in candidates:
        results = upload.get("processing_results") or {}
        if isinstance(results, str):
            try:
                results = json.loads(results)
            except (json.JSONDecodeError, TypeError):
                continue
        measurements_list = results.get("measurements", [])
        if not measurements_list:
            continue
        # Look for the "Average" entry
        for entry in measurements_list:
            if entry.get("label") == "Average":
                return entry.get("results", {})
        # Fallback: last entry
        return measurements_list[-1].get("results", {})

    return None
