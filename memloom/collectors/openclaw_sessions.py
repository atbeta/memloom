"""OpenClaw session trajectory collector.

Reads ``*.trajectory.jsonl`` files from OpenClaw's session storage and
emits one ``MemoryRecord`` per conversation turn (one user prompt + one
model response). The raw trajectory events are preserved in ``raw_meta``
for forensic queries.

Why this matters
----------------
OpenClaw soft-deletes sessions after 30 days, then permanently removes
them. Anything valuable said in a session is lost unless we extract it
to a separate, durable store first. This collector is that bridge.

File layout
-----------
``~/.openclaw/agents/main/sessions/<sessionId>.trajectory.jsonl``

Each line is one OTel-style event::

    {
      "type": "prompt.submitted" | "model.completed" | "session.started" | ...,
      "ts": "2026-07-18T03:11:00.000Z",
      "sessionId": "<uuid>",
      "runId": "<uuid>",          # groups events of one turn
      "workspaceDir": "/path/...",
      "modelId": "...",
      "data": { ... type-specific ... }
    }

Pairing strategy
----------------
Events are grouped by ``runId`` (one per turn). For each run we emit one
``MemoryRecord`` with::

    role           = "conversation_turn"
    content        = "USER: <prompt>\\n\\nASSISTANT: <response>"
    occurred_at    = prompt.submitted ts
    source_key     = "<sessionId>#<runId>"
    raw_meta       = full event payloads for the run
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Iterator

from ..records import MemoryRecord, Source, Watermark
from ..transport.base import Transport
from .base import AgentAdapter, CollectorContext


_FILENAME_RE = re.compile(
    r"^(?P<sid>[0-9a-f-]+)\.trajectory\.jsonl$"
)


class OpenClawSessionAdapter(AgentAdapter):
    name = "openclaw_session"
    default_paths = ["~/.openclaw/agents/main/sessions/"]

    def __init__(self, options: dict | None = None) -> None:
        super().__init__(options)
        opts = options or {}
        self._include_deleted = bool(opts.get("include_deleted", False))
        self._sessions_dir = (
            opts.get("sessions_dir")
            or os.environ.get("OPENCLAW_SESSIONS_DIR")
            or "~/.openclaw/agents/main/sessions"
        )

    # ---- Discover ----

    def discover(self, transport: Transport) -> list[Source]:
        paths: list[Source] = []
        sdir = Path(self._sessions_dir).expanduser()
        if not sdir.exists():
            return []
        for p in sorted(sdir.glob("*.trajectory.jsonl")):
            if ".deleted." in p.name and not self._include_deleted:
                continue
            m = _FILENAME_RE.match(p.name)
            if not m:
                continue
            paths.append(Source(
                source=self.name,
                host="?",
                transport=transport.name,
                path=str(p),
            ))
        return paths

    # ---- Pull ----

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
        h = _content_hash(raw)
        if last_wm and last_wm.last_hash == h:
            return

        session_id = PurePosixPath(source.path).stem.replace(".trajectory", "")
        workspace_dir = ""

        # Bucket events by runId
        runs: dict[str, dict] = defaultdict(dict)
        session_meta: dict = {}
        try:
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                ev = json.loads(line)
                et = ev.get("type", "")
                rid = ev.get("runId") or ev.get("traceId") or "_"
                if not workspace_dir:
                    workspace_dir = ev.get("workspaceDir") or ""
                if et in ("prompt.submitted", "model.completed", "trace.artifacts"):
                    runs[rid][et] = ev
                elif et == "session.started":
                    session_meta = ev.get("data", {}) or {}
                elif et == "trace.metadata":
                    runs[rid]["__metadata__"] = ev
        except (json.JSONDecodeError, KeyError):
            return

        # Emit one record per run
        new_count = 0
        for rid in sorted(runs.keys()):
            payload = runs[rid]
            if rid == "_" or "__metadata__" == rid:
                continue
            prompt_ev = payload.get("prompt.submitted")
            response_ev = payload.get("model.completed")
            if not prompt_ev and not response_ev:
                continue

            prompt_text = ""
            if prompt_ev:
                prompt_text = (prompt_ev.get("data") or {}).get("prompt") or ""

            response_text = ""
            if response_ev:
                data = response_ev.get("data") or {}
                texts = data.get("assistantTexts") or []
                response_text = "\n".join(t for t in texts if t)

            if not prompt_text and not response_text:
                continue

            ts = _parse_ts(
                (prompt_ev or response_ev).get("ts")
            )
            model_id = (prompt_ev or response_ev).get("modelId") or ""

            parts = []
            if prompt_text:
                parts.append(f"**USER** ({_fmt_ts_short(ts)}):\n{prompt_text}")
            if response_text:
                short_model = (model_id or "?").split("/")[-1]
                parts.append(f"**ASSISTANT** ({short_model}):\n{response_text}")
            content = "\n\n".join(parts)

            rec = MemoryRecord(
                source=self.name,
                source_key=f"{session_id}#{rid}",
                agent=f"openclaw:{model_id}" if model_id else "openclaw",
                project=PurePosixPath(workspace_dir).name if workspace_dir else None,
                visibility="personal",
                captured_at=self.now_ms(),
                occurred_at=ts,
                role="conversation_turn",
                content=content,
                raw_meta={
                    "session_id": session_id,
                    "run_id": rid,
                    "workspace_dir": workspace_dir,
                    "model_id": model_id,
                    "provider": (prompt_ev or response_ev or {}).get("provider", ""),
                    "session_meta": session_meta,
                    "prompt_data": (prompt_ev.get("data") if prompt_ev else {}) or {},
                    "response_data": (response_ev.get("data") if response_ev else {}) or {},
                },
            )
            new_count += 1
            yield rec, Watermark(
                source=self.name,
                source_key=source.path,
                last_seen_ms=stat.mtime_ms,
                last_hash=h,
                last_run_id=ctx.run_id,
            )

        if new_count == 0:
            yield MemoryRecord(
                source=self.name,
                source_key=source.path,
                agent="openclaw",
                role="_skip_marker",
                content="",
                content_hash=h,
                captured_at=self.now_ms(),
                occurred_at=stat.mtime_ms,
            ), Watermark(
                source=self.name,
                source_key=source.path,
                last_seen_ms=stat.mtime_ms,
                last_hash=h,
                last_run_id=ctx.run_id,
            )


def _content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_ts(s) -> int | None:
    if not s:
        return None
    try:
        import datetime as _dt
        return int(_dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def _fmt_ts_short(ms: int | None) -> str:
    if not ms:
        return "?"
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ms / 1000).isoformat(timespec="seconds")


__all__ = ["OpenClawSessionAdapter"]