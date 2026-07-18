"""SyncAdapter base class — for push-based agent data extraction."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memloom.records import MemoryRecord


# ── Watermark (simpler than the collector Watermark — just a cursor) ─────────

@dataclass
class SyncWatermark:
    source_type: str
    cursor_ms: int = 0  # epoch ms — "everything after this is new"


class WatermarkStore:
    """File-backed watermark store: ~/.memloom-sync/watermarks.json"""

    def __init__(self, state_dir: Path):
        self._file = state_dir / "watermarks.json"

    def load(self) -> dict[str, int]:
        if self._file.exists():
            return json.loads(self._file.read_text())
        return {}

    def save(self, wm: dict[str, int]) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(wm))


# ── Base adapter ────────────────────────────────────────────────────────────

class SyncAdapter(ABC):
    """Base for push adapters that read local agent stores.

    Subclasses:
      - read from a local path (SQLite, JSON files, directories)
      - produce MemoryRecord objects
      - report the latest cursor for incremental runs
    """

    source_type: str = ""  # e.g. "opencode", "codex"
    source_path: str = ""  # config-provided path (db file or directory)

    def __init__(self, source_path: str):
        self.source_path = os.path.expanduser(source_path)

    @abstractmethod
    def extract(self, since_ms: int | None = None) -> list[MemoryRecord]:
        """Read all records since *since_ms* (None = full)."""

    @abstractmethod
    def get_latest_cursor(self) -> int:
        """Return ms epoch of the newest record's timestamp."""
