"""Generic JSONL collector.

Reads any newline-delimited JSON file where each line has at least
``role`` (or ``type``) and ``content`` (or ``message``). Useful as a fallback
for agents we haven't written a specific adapter for, or for ad-hoc imports.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import PurePosixPath

from ..records import MemoryRecord, Source, Watermark
from ..transport.base import Transport
from .base import AgentAdapter, CollectorContext


class GenericJSONLAdapter(AgentAdapter):
    name = "generic_jsonl"

    def discover(self, transport: Transport) -> list[Source]:
        patterns = self.options.get("paths") or []
        out: list[Source] = []
        for p in patterns:
            try:
                files = transport.glob(p)
            except Exception:
                continue
            for f in files:
                if f.endswith(".jsonl") or f.endswith(".ndjson"):
                    out.append(Source(
                        source=self.name,
                        host="?",
                        transport=transport.name,
                        path=f,
                        extra={"pattern": p},
                    ))
        return out

    def pull(
        self,
        source: Source,
        ctx: CollectorContext,
    ) -> Iterator[tuple[MemoryRecord, Watermark]]:
        try:
            stat = ctx.transport.stat(source.path)
        except FileNotFoundError:
            return
        if not stat.is_file:
            return

        last_wm = ctx.last_watermarks.get(source.source_key)
        if last_wm and last_wm.last_seen_ms >= stat.mtime_ms and last_wm.last_hash:
            return

        raw = ctx.transport.read_text(source.path)
        h = _sha256(raw)
        if last_wm and last_wm.last_hash == h:
            return

        for lineno, line in enumerate(raw.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue

            role = obj.get("role") or obj.get("type") or "entry"
            content = obj.get("content") or obj.get("message") or obj.get("text")
            if isinstance(content, (dict, list)):
                content = json.dumps(content, ensure_ascii=False)
            if not content:
                continue

            yield MemoryRecord(
                source=self.name,
                source_key=f"{source.path}#{lineno}",
                agent=obj.get("agent") or self.options.get("agent_name", "unknown"),
                project=obj.get("project") or PurePosixPath(source.path).parent.name,
                visibility="personal",
                captured_at=self.now_ms(),
                occurred_at=obj.get("timestamp_ms") or (int(obj["timestamp"]) if isinstance(obj.get("timestamp"), (int, float)) else None),
                role=role if isinstance(role, str) else "entry",
                content=content if isinstance(content, str) else str(content),
                raw_meta={k: v for k, v in obj.items() if k not in {"content", "message", "text"}},
            ), Watermark(
                source=self.name,
                source_key=f"{source.path}#{lineno}",
                last_seen_ms=stat.mtime_ms,
                last_hash=h,
                last_run_id=ctx.run_id,
            )


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = ["GenericJSONLAdapter"]
