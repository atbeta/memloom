"""Hermes sync adapter — reads state.db (sessions + messages tables).

Source: Hermes ~/.hermes/state.db
Messages have role (user/assistant) and plain text content.
"""

from __future__ import annotations

import os
import sqlite3

from memloom.sync.adapter import SyncAdapter


class HermesAdapter(SyncAdapter):
    source_type = "hermes"

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
            where = "AND m.timestamp > ?"
            params.append(since_ms / 1000)

        cur.execute(
            f"""SELECT s.id as session_id, s.model, s.source, s.started_at,
                       m.role, m.content, m.timestamp, m.tool_name
                FROM messages m
                JOIN sessions s ON m.session_id = s.id
                WHERE 1=1 {where}
                ORDER BY s.id, m.timestamp""",
            params,
        )
        rows = cur.fetchall()

        # Group by session_id
        sessions: dict[str, list] = {}
        for r in rows:
            sessions.setdefault(r["session_id"], []).append(r)

        for sid, msgs in sessions.items():
            body = self._render_conversation(msgs)
            if not body.strip():
                continue

            first = msgs[0]
            records.append(MemoryRecord(
                source=self.source_type,
                source_key=sid,
                content=body,
                role="conversation_turn",
                agent=f"hermes:{first['model'] or ''}" if first["model"] else "hermes",
                occurred_at=int(first["timestamp"] * 1000) if first["timestamp"] else None,
                raw_meta={
                    "session_id": sid,
                    "model": first["model"] or "",
                    "source": first["source"] or "",
                    "message_count": len(msgs),
                },
            ))

        conn.close()
        return records

    @staticmethod
    def _render_conversation(msgs) -> str:
        lines: list[str] = []
        for m in msgs:
            role = m["role"] or "unknown"
            content = m["content"] or ""
            if content.strip():
                lines.append(f"## {role}\n")
                lines.append(content.strip())
                lines.append("")
        return "\n".join(lines)

    def get_latest_cursor(self) -> int:
        if not os.path.exists(self.source_path):
            return 0
        conn = sqlite3.connect(self.source_path)
        cur = conn.cursor()
        cur.execute("SELECT MAX(timestamp) FROM messages")
        row = cur.fetchone()
        conn.close()
        return int((row[0] or 0) * 1000) if row and row[0] else 0
