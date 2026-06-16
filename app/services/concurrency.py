"""
Shared concurrency primitives for expensive AI work.

The LLM calls are synchronous Ollama HTTP requests dispatched via
``asyncio.to_thread``. Without a bound, a traffic spike would spawn unbounded
threads, exhaust the default thread-pool, and stall the entire event loop.
A single shared semaphore caps concurrent generations across BOTH the chat and
recommendation endpoints so one heavy user can't freeze everyone.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.config import settings
from app.services.metrics import metrics

_max = max(1, int(getattr(settings, "llm_max_concurrency", 2)))
llm_semaphore = asyncio.Semaphore(_max)


@asynccontextmanager
async def llm_slot(label: str = "llm") -> AsyncIterator[None]:
    """Acquire an LLM concurrency slot, recording queue-wait time.

    Usage:
        async with llm_slot("recommendations"):
            await asyncio.to_thread(llm_manager.generate, ...)
    """
    waiting = llm_semaphore.locked()
    if waiting:
        metrics.incr(f"{label}.llm_queued")
    with metrics.timer(f"{label}.llm_wait_seconds"):
        await llm_semaphore.acquire()
    try:
        yield
    finally:
        llm_semaphore.release()
