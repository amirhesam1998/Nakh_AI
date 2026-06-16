"""
Upload metadata store with a per-user index.

Previously, listing a user's uploads globbed and JSON-parsed *every* metadata
file on disk on every recommendation / chat / list request — an O(total
uploads) full scan that becomes a hard bottleneck as the catalog of users
grows. This module keeps a small per-user index (a list of upload ids) so a
lookup is O(that user's uploads).

Backward compatible: if the index for a user is missing (existing installs,
files written before this change), it is transparently rebuilt from the
on-disk files the first time it's needed.

The historical helper names in ``app.api.uploads`` (`_save_metadata`,
`_load_metadata`, ...) now delegate here so existing imports keep working.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

METADATA_DIR: Path = settings.media_path / "metadata"
INDEX_DIR: Path = METADATA_DIR / "_index"

_lock = threading.Lock()


def _ensure_dirs() -> None:
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)


def _meta_path(upload_id: str) -> Path:
    return METADATA_DIR / f"{upload_id}.json"


def _user_index_path(user_id: str) -> Path:
    return INDEX_DIR / f"user_{user_id}.json"


def _read_index(user_id: str) -> Optional[List[str]]:
    path = _user_index_path(user_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _write_index(user_id: str, ids: List[str]) -> None:
    _ensure_dirs()
    path = _user_index_path(user_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ids), encoding="utf-8")
    tmp.replace(path)


def _rebuild_all_indexes() -> dict[str, List[str]]:
    """One-time migration: scan every metadata file and build per-user indexes.

    Returns the {user_id: [upload_id, ...]} mapping (newest-first).
    """
    _ensure_dirs()
    by_user: dict[str, list[tuple[str, str]]] = {}  # user -> [(uploaded_at, id)]
    for path in METADATA_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        uid = str(data.get("user_id"))
        if not uid or uid == "None":
            continue
        by_user.setdefault(uid, []).append(
            (data.get("uploaded_at", ""), path.stem)
        )

    result: dict[str, List[str]] = {}
    for uid, entries in by_user.items():
        entries.sort(key=lambda t: t[0], reverse=True)
        ids = [e[1] for e in entries]
        _write_index(uid, ids)
        result[uid] = ids
    logger.info("Rebuilt upload indexes for %d users", len(result))
    return result


def save_metadata(upload_id: str, data: dict) -> None:
    """Persist upload metadata and keep the owning user's index current."""
    _ensure_dirs()
    target = _meta_path(upload_id)
    tmp = METADATA_DIR / f"{upload_id}.json.tmp"
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(target)

    user_id = data.get("user_id")
    if user_id is None:
        return
    user_id = str(user_id)
    with _lock:
        ids = _read_index(user_id)
        if ids is None:
            # Index missing — rebuild from disk (covers pre-existing installs).
            ids = _rebuild_all_indexes().get(user_id, [])
        if upload_id not in ids:
            ids.insert(0, upload_id)  # newest-first
            _write_index(user_id, ids)


def load_metadata(upload_id: str) -> Optional[dict]:
    path = _meta_path(upload_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def delete_metadata(upload_id: str) -> None:
    # Read owner before deleting so we can prune the index.
    data = load_metadata(upload_id)
    path = _meta_path(upload_id)
    if path.exists():
        path.unlink()
    if data and data.get("user_id") is not None:
        user_id = str(data["user_id"])
        with _lock:
            ids = _read_index(user_id)
            if ids is not None and upload_id in ids:
                ids = [i for i in ids if i != upload_id]
                _write_index(user_id, ids)


def list_user_metadata(user_id: str) -> List[dict]:
    """Return a user's uploads (newest-first) using the index, not a full scan."""
    user_id = str(user_id)
    ids = _read_index(user_id)
    if ids is None:
        # Lazy migration for pre-existing data.
        with _lock:
            ids = _rebuild_all_indexes().get(user_id, [])

    uploads: List[dict] = []
    stale: List[str] = []
    for uid in ids:
        data = load_metadata(uid)
        if data is None:
            stale.append(uid)
            continue
        uploads.append(data)

    # Self-heal: drop index entries whose files vanished.
    if stale:
        with _lock:
            current = _read_index(user_id) or ids
            current = [i for i in current if i not in stale]
            _write_index(user_id, current)

    uploads.sort(key=lambda u: u.get("uploaded_at", ""), reverse=True)
    return uploads
