"""Base AgentAdapter — every collector subclasses this.

A collector is responsible for ONE agent's data on ONE host. It knows:
  * where that agent stores its data on disk/remote
  * how to parse each item into a MemoryRecord
  * how to track incremental progress (its own watermark scheme)

The pipeline knows nothing about agents. Collectors are pluggable.
"""
from __future__ import annotations

import abc
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from ..records import MemoryRecord, Source, Watermark
from ..transport.base import Transport


@dataclass
class CollectorContext:
    """Per-run state passed into a collector's collect() method."""
    transport: Transport
    run_id: str
    last_watermarks: dict[str, Watermark]   # keyed by source_key


class AgentAdapter(abc.ABC):
    """Subclass and implement ``discover`` + ``pull``."""

    #: Stable name (matches config ``agents[].type``).
    name: str = ""

    #: Default paths (relative to $HOME unless absolute). Can be overridden in config.
    default_paths: list[str] = []

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self.options = options or {}

    # ---- Lifecycle hooks ----

    def setup(self, transport: Transport) -> None:
        """Optional one-time setup (e.g., verify agent is installed)."""
        return None

    # ---- Discovery ----

    @abc.abstractmethod
    def discover(self, transport: Transport) -> list[Source]:
        """List the Sources this collector can read on this transport."""
        ...

    # ---- Pull ----

    @abc.abstractmethod
    def pull(
        self,
        source: Source,
        ctx: CollectorContext,
    ) -> Iterator[tuple[MemoryRecord, Watermark]]:
        """Yield (record, new_watermark) pairs.

        Watermarks enable incremental collection. A collector that doesn't need
        them can yield one watermark per source per run (last-seen mtime).
        """
        ...

    # ---- Helpers ----

    def now_ms(self) -> int:
        return int(time.time() * 1000)


__all__ = ["AgentAdapter", "CollectorContext"]
