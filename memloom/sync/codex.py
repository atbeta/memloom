"""Codex CLI sync adapter — reads state_5.sqlite + rollout JSONL."""

from __future__ import annotations

import json
import os
import sqlite3

from memloom.sync.adapter import SyncAdapter


class CodexAdapter(SyncAdapter):
    source_type = "codex"

    def extract(self, since_ms: int | None = None) -> list:
        from memloom.records import MemoryRecord

        records: list[MemoryRecord] = []
        if not os.path.exists(self.source_path):
            return records

        conn = sqlite3.connect(self.source_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        where = ""
        params: list = []
        if since_ms:
            where = "WHERE created_at > ?"
            params = [int(since_ms / 1000)]

        cur.execute(
            f"""SELECT id, title, created_at, cwd, model_provider, model, rollout_path
                FROM threads {where}
                ORDER BY created_at""",
            params,
        )
        threads = cur.fetchall()
        conn.close()

        for t in threads:
            rpath = t["rollout_path"]
            if not rpath or not os.path.exists(rpath):
                continue

            body = self._parse_rollout(rpath)
            if not body.strip():
                continue

            project = os.path.basename((t["cwd"] or "").rstrip("/")) or ""
            records.append(MemoryRecord(
                source=self.source_type,
                source_key=t["id"],
                content=body,
                role="conversation_turn",
                agent=f"codex:{t['model_provider'] or ''}:{t['model'] or ''}",
                project=project or None,
                occurred_at=(t["created_at"] or 0) * 1000,
                raw_meta={
                    "title": t["title"] or "",
                    "model": t["model"] or "",
                    "provider": t["model_provider"] or "",
                    "thread_id": t["id"],
                },
            ))

        return records

    @staticmethod
    def _parse_rollout(path: str) -> str:
        lines: list[str] = []
        with open(path) as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                tp = obj.get("type", "")
                pl = obj.get("payload", obj)

                if tp == "event_msg":
                    ev = pl.get("type", "")
                    if ev == "user_message":
                        msg = pl.get("message", "")
                        if msg.strip():
                            lines.append("## User\n")
                            lines.append(msg.strip())
                            lines.append("")
                    elif ev == "agent_message":
                        msg = pl.get("message", "")
                        if msg.strip():
                            lines.append("## Assistant\n")
                            lines.append(msg.strip())
                            lines.append("")
                    elif ev == "agent_reasoning":
                        text = pl.get("text", "")
                        if text.strip():
                            lines.append("> **Reasoning:**")
                            for ln in text.strip().split("\n"):
                                lines.append(f"> {ln}")
                            lines.append("")
        return "\n".join(lines)

    def get_latest_cursor(self) -> int:
        if not os.path.exists(self.source_path):
            return 0
        conn = sqlite3.connect(self.source_path)
        cur = conn.cursor()
        cur.execute("SELECT MAX(created_at) FROM threads")
        row = cur.fetchone()
        conn.close()
        return ((row[0] or 0) * 1000) if row else 0
