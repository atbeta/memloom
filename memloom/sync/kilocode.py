"""Kilo Code sync adapter — reads tasks/{id}/api_conversation_history.json."""

from __future__ import annotations

import json
import os
from pathlib import Path

from memloom.sync.adapter import SyncAdapter


class KiloCodeAdapter(SyncAdapter):
    source_type = "kilocode"

    def extract(self, since_ms: int | None = None) -> list:
        from memloom.records import MemoryRecord

        records: list[MemoryRecord] = []
        tasks_dir = Path(self.source_path)
        if not tasks_dir.is_dir():
            return records

        for task_dir in sorted(tasks_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            conv_file = task_dir / "api_conversation_history.json"
            meta_file = task_dir / "task_metadata.json"
            if not conv_file.exists():
                continue

            mtime_ms = int(conv_file.stat().st_mtime * 1000)
            if since_ms and mtime_ms < since_ms:
                continue

            try:
                messages = json.loads(conv_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if not messages:
                continue

            title = ""
            if meta_file.exists():
                try:
                    title = json.loads(meta_file.read_text()).get("taskTitle", "")
                except (json.JSONDecodeError, OSError):
                    pass

            body = self._render_conversation(messages)
            if not body.strip():
                continue

            # Find first user message ts
            first_ts = None
            for msg in messages:
                role = msg.get("role", "")
                ts = msg.get("ts", 0)
                if ts and role == "user":
                    first_ts = int(ts * 1000) if ts < 9999999999 else ts
                    break

            records.append(MemoryRecord(
                source=self.source_type,
                source_key=task_dir.name,
                content=body,
                role="conversation_turn",
                agent="kilocode",
                occurred_at=first_ts,
                raw_meta={
                    "title": title or task_dir.name,
                    "message_count": len(messages),
                },
            ))

        return records

    @staticmethod
    def _render_conversation(messages: list[dict]) -> str:
        lines: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", [])
            text = " ".join(
                c.get("text", "") for c in content
                if isinstance(c, dict) and c.get("type") == "text"
            )
            if text.strip():
                lines.append(f"## {role}\n")
                lines.append(text.strip())
                lines.append("")
        return "\n".join(lines)

    def get_latest_cursor(self) -> int:
        tasks_dir = Path(self.source_path)
        if not tasks_dir.is_dir():
            return 0
        latest = 0
        for task_dir in tasks_dir.iterdir():
            conv_file = task_dir / "api_conversation_history.json"
            if conv_file.exists():
                mtime = int(conv_file.stat().st_mtime * 1000)
                latest = max(latest, mtime)
        return latest
