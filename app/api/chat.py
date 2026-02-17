"""
Chat API endpoints.

Provides endpoints for:
- Sending messages to the chatbot
- Managing chat sessions
- Managing user preferences
- Getting chat history
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import get_current_active_user
from app.database import RedisStorage
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


@router.post("/sessions", response_model=ChatSessionResponse)
async def create_chat_session(
    session_config: ChatSessionCreate,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Create a new chat session.

    A chat session maintains conversation history and context.
    You can have multiple sessions.
    """
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
    """
    List user's chat sessions.
    """
    from app.database import get_redis
    import json

    redis = await get_redis()
    session_ids = await redis.lrange(
        f"user_chat_sessions:{current_user['id']}",
        0, limit - 1
    )

    sessions = []
    for session_id in session_ids:
        session = await chat_service.get_session(session_id)
        if session:
            sessions.append(session)

    return sessions


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_chat_session(
    session_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Get a specific chat session.
    """
    session = await chat_service.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found"
        )

    if session.user_id != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    return session


@router.delete("/sessions/{session_id}")
async def delete_chat_session(
    session_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Delete a chat session and its history.
    """
    success = await chat_service.delete_session(session_id, current_user["id"])

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found or access denied"
        )

    return {"message": "Session deleted successfully"}


@router.post("/message", response_model=ChatMessageResponse)
async def send_message(
    request: ChatMessageRequest,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Send a message to the chatbot and receive a response.

    The chatbot can:
    - Discuss your body measurements
    - Help with clothing preferences
    - Recommend products from the shop
    - Answer questions about fabrics and styles

    If session_id is not provided, uses or creates a default session.
    """
    # Get user's measurements if available
    measurements = await _get_user_measurements(current_user["id"])

    # Get user's preferences
    preferences = await chat_service.get_user_preferences(current_user["id"])

    # Send message and get response
    user_msg, assistant_msg, recommendations = await chat_service.send_message(
        user_id=current_user["id"],
        message=request.message,
        session_id=request.session_id,
        measurements=measurements,
        preferences=preferences,
    )

    # Get the session ID
    session = await chat_service.get_or_create_session(
        current_user["id"],
        request.session_id
    )

    return ChatMessageResponse(
        session_id=session.session_id,
        user_message=user_msg,
        assistant_message=assistant_msg,
        recommended_products=recommendations,
    )


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    session_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Get chat history for a session.
    """
    history = await chat_service.get_chat_history(session_id, current_user["id"])

    if not history:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found or access denied"
        )

    return history


@router.delete("/history/{session_id}")
async def clear_chat_history(
    session_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Clear chat history for a session (keeps the session).
    """
    success = await chat_service.clear_chat_history(session_id, current_user["id"])

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found or access denied"
        )

    return {"message": "Chat history cleared successfully"}


@router.get("/preferences", response_model=Optional[UserPreferences])
async def get_preferences(
    current_user: dict = Depends(get_current_active_user),
):
    """
    Get user's clothing preferences.

    Preferences are used to personalize chatbot responses
    and product recommendations.
    """
    return await chat_service.get_user_preferences(current_user["id"])


@router.put("/preferences", response_model=UserPreferences)
async def update_preferences(
    preferences: UserPreferencesUpdate,
    current_user: dict = Depends(get_current_active_user),
):
    """
    Update user's clothing preferences.

    These preferences help the chatbot provide better recommendations.
    """
    # Get existing preferences or create new
    existing = await chat_service.get_user_preferences(current_user["id"])

    if existing:
        # Merge with existing
        updated_data = existing.model_dump()
        update_dict = preferences.model_dump(exclude_unset=True)

        for key, value in update_dict.items():
            if value is not None:
                if key == "budget_min" and "budget_max" in update_dict:
                    updated_data["budget_range"] = (
                        update_dict.get("budget_min", 0),
                        update_dict.get("budget_max", float("inf"))
                    )
                elif key not in ["budget_min", "budget_max"]:
                    updated_data[key] = value

        new_preferences = UserPreferences(**updated_data)
    else:
        # Create new preferences
        pref_dict = preferences.model_dump(exclude_unset=True)
        if "budget_min" in pref_dict or "budget_max" in pref_dict:
            pref_dict["budget_range"] = (
                pref_dict.pop("budget_min", 0),
                pref_dict.pop("budget_max", float("inf"))
            )
        new_preferences = UserPreferences(**pref_dict)

    return await chat_service.update_user_preferences(
        current_user["id"],
        new_preferences
    )


@router.delete("/preferences")
async def delete_preferences(
    current_user: dict = Depends(get_current_active_user),
):
    """
    Delete user's clothing preferences.
    """
    from app.database import get_redis

    redis = await get_redis()
    await redis.delete(f"user_preferences:{current_user['id']}")

    return {"message": "Preferences deleted successfully"}


async def _get_user_measurements(user_id: str) -> Optional[dict]:
    """
    Get user's latest measurements from processed uploads.

    This fetches the most recent measurement results for the user.
    """
    from app.database import get_redis
    import json

    redis = await get_redis()

    # Get user's uploads
    upload_ids = await redis.lrange(f"user_uploads:{user_id}", 0, 10)

    for upload_id in upload_ids:
        upload_data = await redis.get(f"upload:{upload_id}")
        if not upload_data:
            continue

        upload = json.loads(upload_data)

        # Check if processing is completed and has results
        if upload.get("processing_status") == "completed":
            results = upload.get("processing_results", {})
            measurements = results.get("measurements", {})

            if measurements:
                # Return averaged measurements if available
                if "averaged" in measurements:
                    return measurements["averaged"]
                # Otherwise return first available view
                for view in ["front", "tpose", "side"]:
                    if view in measurements:
                        return measurements[view]

    return None
