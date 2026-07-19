"""Hub API key resolution: ingest / read / admin."""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_warned_read_fallback = False


def ingest_key() -> str | None:
    """Key for POST /ingest only."""
    return os.environ.get("MEMLOOM_INGEST_KEY") or None


def read_key() -> str | None:
    """Key for search + MCP. Falls back to ingest key with a one-time warning."""
    global _warned_read_fallback
    key = os.environ.get("MEMLOOM_READ_KEY")
    if key:
        return key
    fallback = ingest_key()
    if fallback and not _warned_read_fallback:
        log.warning(
            "MEMLOOM_READ_KEY unset — falling back to MEMLOOM_INGEST_KEY for read/MCP auth"
        )
        _warned_read_fallback = True
    return fallback


def admin_key() -> str | None:
    """Key for /api/admin. Prefer ADMIN, then INGEST."""
    return os.environ.get("MEMLOOM_ADMIN_KEY") or ingest_key()
