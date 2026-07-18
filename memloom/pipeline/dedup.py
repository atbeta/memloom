"""Content dedup by sha256(content_hash). Pipeline-level filter."""
from __future__ import annotations

from ..records import MemoryRecord


class Deduper:
    """Drop records whose content_hash was seen earlier in this run.

    Note: persistent dedup (across runs) is handled by the store (records.id PK
    + content_hash UNIQUE in the index). This is the in-process safety net.
    """
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def is_new(self, record: MemoryRecord) -> bool:
        h = record.content_hash
        if not h or h in self._seen:
            return False
        self._seen.add(h)
        return True


__all__ = ["Deduper"]
