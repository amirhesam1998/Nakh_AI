"""
Behavioural event collection — the seed of the data flywheel.

We previously discarded the exact signals needed to ever improve recommendation
ranking and size accuracy: which products were shown, which were clicked/bought,
and whether the recommended size actually fit. This module records those events
to an append-only JSONL log (one file per UTC day) and, when the Laravel
internal API is configured, mirrors them to the CMS for durable, queryable
storage.

Design goals:
- Never throw into the request path. Event recording is best-effort.
- Cheap: append a line; optional fire-and-forget HTTP mirror.
- Structured & forward-compatible: every event has type, ts, user_id, payload.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Canonical event types. Use these constants so analytics queries stay stable.
EVENT_RECOMMENDATION_SHOWN = "recommendation_shown"
EVENT_PRODUCT_CLICKED = "product_clicked"
EVENT_ADDED_TO_CART = "added_to_cart"
EVENT_PURCHASED = "purchased"
EVENT_SIZE_FEEDBACK = "size_feedback"          # recommended vs chosen vs returned
EVENT_FIT_FEEDBACK = "fit_feedback"            # "too tight" / "perfect" / "too loose"
EVENT_MEASUREMENT_COMPLETED = "measurement_completed"

_EVENTS_DIR: Path = settings.media_path / "events"
_lock = threading.Lock()


def _ensure_dir() -> Path:
    _EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    return _EVENTS_DIR


def _log_path() -> Path:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _ensure_dir() / f"events-{day}.jsonl"


class _InternalForwarder:
    """Best-effort mirror of events to the Laravel internal API."""

    def __init__(self, base_url: str, api_key: str) -> None:
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
                timeout=httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0),
            )
        return self._client

    async def send(self, event: dict) -> None:
        try:
            client = await self._get_client()
            await client.post("/api/internal/events", json=event)
        except Exception as e:  # never propagate into the request path
            logger.debug("Event forward failed (%s): %s", type(e).__name__, e)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


_forwarder: Optional[_InternalForwarder] = None
if getattr(settings, "internal_api_url", ""):
    _forwarder = _InternalForwarder(settings.internal_api_url, settings.internal_api_key)


def _write_local(event: dict) -> None:
    line = json.dumps(event, ensure_ascii=False, default=str)
    with _lock:
        with _log_path().open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def record(
    event_type: str,
    user_id: Optional[str] = None,
    **payload: Any,
) -> dict:
    """Record an event synchronously to the local JSONL log.

    Returns the event dict (so callers can also forward it). Best-effort —
    swallows all errors so analytics never breaks a user request.
    """
    event = {
        "type": event_type,
        "ts": datetime.now(timezone.utc).isoformat(),
        "user_id": str(user_id) if user_id is not None else None,
        "payload": payload,
    }
    if not getattr(settings, "event_log_enabled", True):
        return event
    try:
        _write_local(event)
    except Exception as e:
        logger.debug("Local event write failed (%s): %s", type(e).__name__, e)
    return event


async def record_async(
    event_type: str,
    user_id: Optional[str] = None,
    **payload: Any,
) -> None:
    """Record locally and mirror to the internal API (fire-and-forget)."""
    event = record(event_type, user_id, **payload)
    if _forwarder is not None:
        await _forwarder.send(event)


async def close() -> None:
    if _forwarder is not None:
        await _forwarder.close()
