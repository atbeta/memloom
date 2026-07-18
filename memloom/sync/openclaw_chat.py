"""OpenClaw native chat sync adapter — reads *.jsonl session files (NOT trajectory).

Source: OpenClaw agents/main/sessions/*.jsonl
Each line is one event: session, message, model_change, etc.
Message events have role + content in the same parts format as OpenCode.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from memloom.sync.adapter import SyncAdapter


class OpenClawChatAdapter(SyncAdapter):
    source_type = "openclaw_chat"

    def extract(self, since_ms: int | None = None) -> list:
        from memloom.records import MemoryRecord

        records: list[MemoryRecord] = []
        sessions_dir = Path(self.source_path).expanduser()
        if not sessions_dir.is_dir():
            return records

        for jsonl_file in sorted(sessions_dir.glob("*.jsonl")):
            if ".trajectory." in jsonl_file.name or ".deleted." in jsonl_file.name:
                continue
            mtime_ms = int(jsonl_file.stat().st_mtime * 1000)
            if since_ms and mtime_ms < since_ms:
                continue

            try:
                events = []
                for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            except OSError:
                continue

            body = self._render_conversation(events)
            if not body.strip():
                continue

            session_id = jsonl_file.stem
            workspace_dir = ""
            model_id = ""
            provider = ""
            first_ts = None

            for ev in events:
                et = ev.get("type", "")
                if et == "session":
                    workspace_dir = ev.get("cwd", "") or ""
                elif et == "model_change":
                    model_id = ev.get("modelId", "")
                    provider = ev.get("provider", "")
                ts = ev.get("timestamp", "")
                if ts and not first_ts:
                    first_ts = _parse_ts(ts)

            records.append(MemoryRecord(
                source=self.source_type,
                source_key=session_id,
                content=body,
                role="conversation_turn",
                agent=f"openclaw:{provider}:{model_id}" if model_id else "openclaw",
                project=Path(workspace_dir).name if workspace_dir else None,
                occurred_at=first_ts,
                raw_meta={
                    "session_id": session_id,
                    "workspace_dir": workspace_dir,
                    "model_id": model_id,
                    "provider": provider,
                },
            ))

        return records

    @staticmethod
    def _render_conversation(events: list[dict]) -> str:
        lines: list[str] = []
        for ev in events:
            if ev.get("type") != "message":
                continue
            msg = ev.get("message", {})
            role = msg.get("role", "unknown")
            content = msg.get("content", [])
            texts = []
            for c in content:
                if isinstance(c, dict):
                    t = c.get("text") or c.get("thinking") or ""
                    if t.strip():
                        texts.append(t.strip())
            text = "\n".join(texts)
            if text:
                lines.append(f"## {role}\n")
                lines.append(text)
                lines.append("")
        return "\n".join(lines)

    def get_latest_cursor(self) -> int:
        sessions_dir = Path(self.source_path).expanduser()
        if not sessions_dir.is_dir():
            return 0
        latest = 0
        for f in sessions_dir.glob("*.jsonl"):
            if ".trajectory." not in f.name and ".deleted." not in f.name:
                latest = max(latest, int(f.stat().st_mtime * 1000))
        return latest


def _parse_ts(s) -> int | None:
    if not s:
        return None
    try:
        import datetime as _dt
        return int(_dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, TypeError):
        return None
