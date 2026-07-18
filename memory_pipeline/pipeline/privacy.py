"""Privacy filter: strip secrets/PII from record content before persistence.

The intent: anything that hits disk should be safe to grep / push to a vector
store / hand to an embedding model. The filter is conservative — better to
over-redact than leak a credential.

This runs *before* dedup so we never store hashes of original secret content.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..records import MemoryRecord


@dataclass
class PrivacyStats:
    scanned: int = 0
    redacted: int = 0       # records where at least one pattern matched
    substitutions: int = 0  # total pattern replacements across all records

    def merge(self, other: PrivacyStats) -> None:
        self.scanned += other.scanned
        self.redacted += other.redacted if other.redacted else 0
        self.substitutions += other.substitutions


class PrivacyFilter:
    def __init__(self, patterns: list[str], replacement: str = "[REDACTED]") -> None:
        self._compiled = [re.compile(p) for p in patterns]
        self._replacement = replacement

    def filter_record(self, record: MemoryRecord) -> tuple[MemoryRecord, bool]:
        """Return (possibly-mutated record, was_changed)."""
        new_content, n_content = self._scrub(record.content)

        new_meta = dict(record.raw_meta)
        n_meta = 0
        # Scrub string values inside raw_meta (shallow: only top-level string fields)
        for k, v in list(new_meta.items()):
            if isinstance(v, str):
                v2, nv = self._scrub(v)
                if nv:
                    new_meta[k] = v2
                    n_meta += nv

        total = n_content + n_meta
        if total == 0:
            return record, False

        return MemoryRecord(
            source=record.source,
            source_key=record.source_key,
            id=record.id,
            agent=record.agent,
            project=record.project,
            visibility=record.visibility,
            captured_at=record.captured_at,
            occurred_at=record.occurred_at,
            duration_ms=record.duration_ms,
            role=record.role,
            content=new_content,
            raw_meta=new_meta,
            raw_ref=record.raw_ref,
            tags=record.tags,
        ), True

    def _scrub(self, text: str) -> tuple[str, int]:
        n = 0
        for pat in self._compiled:
            text, count = pat.subn(self._replacement, text)
            n += count
        return text, n


__all__ = ["PrivacyFilter", "PrivacyStats"]
