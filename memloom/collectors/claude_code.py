"""Claude Code collector.

Claude Code stores sessions as newline-delimited JSON at::

    ~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl

Each line is a JSON object with at least::

    { "type": "user" | "assistant" | "system" | ...,
      "message": { "role": ..., "content": <str | list of parts> },
      "timestamp": "ISO-8601",
      "sessionId": "...",
      "cwd": "...",
      ... }

Strategy: one MemoryRecord per (session_id, line_index) so we keep fine-grained
retrievability. Aggregate content from message.content (handle both str and
list-of-parts shapes).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
from collections.abc import Iterator
from pathlib import PurePosixPath

from ..records import MemoryRecord, Source, Watermark
from ..transport.base import Transport
from .base import AgentAdapter, CollectorContext


class ClaudeCodeAdapter(AgentAdapter):
    name = "claude_code"
    default_paths = ["~/.claude/projects/**/*.jsonl"]

    def discover(self, transport: Transport) -> list[Source]:
        # We expand ~ at config time; the runner will pass a list of absolute glob roots.
        # Here we accept either a list or a glob string.
        patterns = self.options.get("paths") or self.default_paths
        out: list[Source] = []
        for p in patterns:
            try:
                files = transport.glob(p)
            except Exception:
                continue
            for f in files:
                if not f.endswith(".jsonl"):
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
            return  # unchanged

        session_id = PurePosixPath(source.path).stem

        seen_lines = 0
        emitted = 0
        for lineno, line in enumerate(raw.splitlines()):
            line = line.strip()
            if not line:
                continue
            seen_lines += 1
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

        # Final watermark for the whole file (covers any unprocessed lines)
        yield MemoryRecord(
            source=self.name,
            source_key=f"{source.path}#__summary__",
            agent="claude_code",
            role="_file_summary",
            content=json.dumps({
                "session_id": session_id,
                "lines_seen": seen_lines,
                "records_emitted": emitted,
                "path": source.path,
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
        msg = obj.get("message")
        if not isinstance(msg, dict):
            return None
        role = msg.get("role") or obj.get("type") or "unknown"
        content = _flatten_content(msg.get("content"))
        if not content:
            return None

        ts = _parse_ts(obj.get("timestamp"))
        cwd = obj.get("cwd") or ""

        return MemoryRecord(
            source=self.name,
            source_key=f"{path}#{lineno}",
            agent="claude_code",
            project=_project_from_cwd(cwd),
            visibility="personal",
            captured_at=self.now_ms(),
            occurred_at=ts,
            role=role,
            content=content,
            raw_meta={
                "session_id": session_id,
                "lineno": lineno,
                "cwd": cwd,
                "type": obj.get("type"),
                "uuid": obj.get("uuid"),
                "parentUuid": obj.get("parentUuid"),
                "isMeta": obj.get("isMeta"),
            },
        )


def _flatten_content(content) -> str:
    """Claude Code messages can have content as str or list of parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, dict):
                if p.get("type") == "text":
                    parts.append(p.get("text", ""))
                elif p.get("type") == "tool_use":
                    name = p.get("name", "?")
                    inp = json.dumps(p.get("input", {}), ensure_ascii=False)
                    parts.append(f"[tool_use:{name}] {inp}")
                elif p.get("type") == "tool_result":
                    parts.append(f"[tool_result] {_flatten_content(p.get('content', ''))}")
                else:
                    parts.append(json.dumps(p, ensure_ascii=False))
            elif isinstance(p, str):
                parts.append(p)
        return "\n".join(parts)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _parse_ts(s) -> int | None:
    if not s:
        return None
    try:
        return int(_dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def _project_from_cwd(cwd: str) -> str | None:
    if not cwd:
        return None
    return PurePosixPath(cwd).name or None


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = ["ClaudeCodeAdapter"]
