"""Content denoiser — strip tool output JSON wrapping and other embedding noise.

Purpose
-------
Embedding models (bge-m3) produce poor vectors for JSON-heavy content like:
  {"output": "Host hz\\nHost rack...", "exit_code": 0}

Stripping the JSON wrapping yields clean text that embeds meaningfully.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..records import MemoryRecord, content_hash


# ── Patterns ────────────────────────────────────────────────────────────────

_TOOL_OUTPUT_RE = re.compile(
    r'\{\s*"output"\s*:\s*"((?:[^"\\]|\\.)*)"[\s,]*'
    r'(?:"exit_code"\s*:\s*\d+[\s,]*)?'
    r'(?:"error"\s*:\s*(?:null|"[^"]*")[\s,]*)?\}',
    re.DOTALL,
)

_JSON_BLOCK_RE = re.compile(r'\{[^{}]*"output"[^{}]*\}', re.DOTALL)

_TOOL_HEADER_RE = re.compile(r'^\*\*`[^`]+`\*\*( → .*)?\n', re.MULTILINE)

_EMPTY_TURN_RE = re.compile(
    r'## (user|assistant)\n+\s*(\(empty\)|Hello!?\s*|你好[!！]?\s*|OK\b)\s*\n*(?=\n##|\Z)',
    re.IGNORECASE | re.MULTILINE,
)


# ── Denoiser ────────────────────────────────────────────────────────────────

@dataclass
class DenoiserStats:
    processed: int = 0
    modified: int = 0
    bytes_before: int = 0
    bytes_after: int = 0

    def merge(self, other: DenoiserStats) -> None:
        self.processed += other.processed
        self.modified += other.modified
        self.bytes_before += other.bytes_before
        self.bytes_after += other.bytes_after


class Denoiser:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def denoise(self, content: str) -> tuple[str, bool]:
        """Return (denoised_content, was_changed)."""
        if not content:
            return content, False

        original = content

        # 1) Strip JSON tool output wrapping: {"output": "text", ...} → text
        content = self._unwrap_tool_outputs(content)

        # 2) Remove empty/noise turns
        content = _EMPTY_TURN_RE.sub("", content)

        # 3) Collapse multiple blank lines
        content = re.sub(r'\n{4,}', '\n\n\n', content)

        changed = content.strip() != original.strip()
        return content.strip(), changed

    @staticmethod
    def _unwrap_tool_outputs(text: str) -> str:
        """Strip JSON wrapping around tool outputs while keeping the content."""
        result = []
        last_end = 0

        for m in _JSON_BLOCK_RE.finditer(text):
            # Add text before the match
            result.append(text[last_end:m.start()])
            last_end = m.end()

            block = m.group(0)
            # Extract "output" value via regex (json.loads fails on raw newlines)
            out_match = re.search(r'"output"\s*:\s*"((?:[^"\\]|\\.)*)"', block)
            if out_match:
                # Unescape the output string
                raw = out_match.group(1)
                raw = raw.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"').replace('\\\\', '\\')
                result.append(raw)
            else:
                result.append(block)

        result.append(text[last_end:])
        return ''.join(result)

    def denoise_record(self, record: MemoryRecord) -> tuple[MemoryRecord, bool]:
        """Return (possibly-denoised record, was_changed)."""
        new_content, changed = self.denoise(record.content)
        if not changed:
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
            raw_meta=record.raw_meta,
            raw_ref=record.raw_ref,
            tags=record.tags,
        ), True


__all__ = ["Denoiser", "DenoiserStats"]
