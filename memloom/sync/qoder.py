"""Qoder sync adapter — reads ~/Library/Application Support/QoderWork/data/agents.db."""

from __future__ import annotations

import json
import os
import sqlite3

from memloom.sync.adapter import SyncAdapter


class QoderAdapter(SyncAdapter):
    source_type = "qoder"

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
            where = "AND m.created_at > ?"
            params.append(since_ms)

        cur.execute(
            f"""SELECT c.id as chat_id, c.name as chat_name, c.created_at,
                       p.name as project_name, p.path as project_path,
                       sc.mode as mode,
                       m.role, m.sequence, m.parts, m.searchable_text, m.created_at as msg_created
                FROM messages m
                JOIN chats c ON m.chat_id = c.id
                JOIN projects p ON c.project_id = p.id
                JOIN sub_chats sc ON m.sub_chat_id = sc.id
                WHERE 1=1 {where}
                ORDER BY c.id, sc.id, m.sequence""",
            params,
        )
        rows = cur.fetchall()

        # Group by chat_id
        chats: dict[str, list] = {}
        for r in rows:
            chats.setdefault(r["chat_id"], []).append(r)

        for chat_id, msgs in chats.items():
            first = msgs[0]
            body = self._render_conversation(msgs)
            if not body.strip():
                continue

            records.append(MemoryRecord(
                source=self.source_type,
                source_key=chat_id,
                content=body,
                role="conversation_turn",
                agent=f"qoder:{first['mode'] or 'agent'}",
                project=first["project_name"] or None,
                occurred_at=first["created_at"],
                raw_meta={
                    "title": first["chat_name"] or "",
                    "message_count": len(msgs),
                    "project_path": first["project_path"] or "",
                },
            ))

        conn.close()
        return records

    def _render_conversation(self, msgs) -> str:
        lines: list[str] = []
        for m in msgs:
            role = m["role"] or "unknown"
            lines.append(f"## {role}\n")
            # searchable_text is pre-processed by Qoder
            text = m["searchable_text"] or ""
            if text.strip():
                lines.append(text.strip())
                lines.append("")
        return "\n".join(lines)

    def get_latest_cursor(self) -> int:
        if not os.path.exists(self.source_path):
            return 0
        conn = sqlite3.connect(self.source_path)
        cur = conn.cursor()
        cur.execute("SELECT MAX(created_at) FROM messages")
        row = cur.fetchone()
        conn.close()
        return row[0] if row and row[0] else 0
