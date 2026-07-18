"""Codex CLI collector.

Codex stores sessions as ``rollout-*.jsonl`` under::

    ~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl

Each line is one event. Schema is documented at
https://github.com/openai/codex (see ``codex-rs`` rollout module).

We try to be lenient: extract ``role``, ``content`` (string or array),
``timestamp``, ``cwd`` from whatever shape we find.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from collections.abc import Iterator
from pathlib import PurePosixPath

from ..records import MemoryRecord, Source, Watermark
from ..transport.base import Transport
from .base import AgentAdapter, CollectorContext

_ROLLOUT_RE = re.compile(r"rollout-\d{4}-\d{2}-\d{2}T.*\.jsonl$")


class CodexAdapter(AgentAdapter):
    name = "codex"
    default_paths = ["~/.codex/sessions/**/*.jsonl"]

    def discover(self, transport: Transport) -> list[Source]:
        patterns = self.options.get("paths") or self.default_paths
        out: list[Source] = []
        for p in patterns:
            try:
                files = transport.glob(p)
            except Exception:
                continue
            for f in files:
                if not _ROLLOUT_RE.search(f):
                    continue
                out.append(Source(
                    source=self.name,
                    host="?",
                    transport=transport.name,
                    path=f,
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

        session_id = PurePosixPath(source.path).stem

        emitted = 0
        for lineno, line in enumerate(raw.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            rec = self._line_to_record(obj, source.path, session_id, lineno)
            if rec is None:
                continue
            emitted += 1
            yield rec, Watermark(
                source=self.name,
                source_key=f"{source.path}#{lineno}",
                last_seen_ms=stat.mtime_ms,
                last_hash=h,
                last_run_id=ctx.run_id,
            )

        yield MemoryRecord(
            source=self.name,
            source_key=f"{source.path}#__summary__",
            agent="codex",
            role="_file_summary",
            content=json.dumps({
                "session_id": session_id, "records_emitted": emitted, "path": source.path,
            }, ensure_ascii=False),
            captured_at=self.now_ms(),
            occurred_at=stat.mtime_ms,
        ), Watermark(
            source=self.name,
            source_key=source.path,
            last_seen_ms=stat.mtime_ms,
            last_hash=h,
            last_run_id=ctx.run_id,
        )

    def _line_to_record(self, obj: dict, path: str, session_id: str, lineno: int) -> MemoryRecord | None:
        # Codex rollout events: timestamp, type ("message" / "tool_call" / ...), payload
        ts = _parse_ts(obj.get("timestamp"))
        cwd = obj.get("cwd") or ""
        payload = obj.get("payload") or obj

        role = payload.get("role") or obj.get("type") or "event"
        content = _flatten(payload.get("content") or payload.get("message") or payload.get("text"))
        if not content:
            return None

        return MemoryRecord(
            source=self.name,
            source_key=f"{path}#{lineno}",
            agent="codex",
            project=PurePosixPath(cwd).name if cwd else None,
            visibility="personal",
            captured_at=self.now_ms(),
            occurred_at=ts,
            role=role,
            content=content,
            raw_meta={
                "session_id": session_id,
                "lineno": lineno,
                "cwd": cwd,
                "event_type": obj.get("type"),
            },
        )


def _flatten(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_flatten(p) for p in content if p)
    if isinstance(content, dict):
        if "text" in content:
            return str(content["text"])
        return json.dumps(content, ensure_ascii=False)
    return str(content) if content is not None else ""


def _parse_ts(s) -> int | None:
    if not s:
        return None
    try:
        return int(_dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = ["CodexAdapter"]
