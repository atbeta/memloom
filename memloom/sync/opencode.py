"""OpenCode sync adapter — reads ~/.local/share/opencode/opencode.db."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Optional

from memloom.sync.adapter import SyncAdapter


class OpenCodeAdapter(SyncAdapter):
    source_type = "opencode"
    MAX_TOOL_OUTPUT = 2000  # truncate long tool outputs

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
            where = "WHERE s.time_updated > ? OR s.time_created > ?"
            params = [since_ms, since_ms]

        cur.execute(
            f"""SELECT s.id, s.title, s.time_created, s.time_updated,
                      s.model, s.agent, s.path
               FROM session s {where}
               ORDER BY s.time_created""",
            params,
        )
        sessions = cur.fetchall()

        for s in sessions:
            sid = s["id"]
            cur.execute(
                """SELECT m.id as msg_id, m.time_created as msg_time,
                          json_extract(m.data, '$.role') as role,
                          p.id as part_id, p.time_created as part_time,
                          json_extract(p.data, '$.type') as part_type,
                          p.data as part_data
                   FROM message m
                   JOIN part p ON p.message_id = m.id
                   WHERE m.session_id = ?
                   ORDER BY m.time_created, p.time_created""",
                (sid,),
            )
            rows = cur.fetchall()
            if not rows:
                continue

            body = self._render_conversation(rows)
            if not body.strip():
                continue

            title = s["title"] or "(untitled)"
            project = os.path.basename((s["path"] or "").rstrip("/")) or ""

            records.append(MemoryRecord(
                source=self.source_type,
                source_key=sid,
                content=body,
                role="conversation_turn",
                agent=f"opencode:{s['agent'] or s['model'] or ''}",
                project=project or None,
                occurred_at=s["time_created"],
                raw_meta={
                    "title": title,
                    "model": s["model"] or "",
                    "session_id": sid,
                },
            ))

        conn.close()
        return records

    def _render_conversation(self, rows) -> str:
        """Reconstruct full conversation from session -> message -> part rows."""
        turns: list[tuple[str, list[dict]]] = []
        current_role: Optional[str] = None
        current_parts: list[dict] = []

        for r in rows:
            role = r["role"]
            pt = r["part_type"]
            try:
                pd = json.loads(r["part_data"])
            except json.JSONDecodeError:
                pd = {}

            if role != current_role and current_parts:
                turns.append((current_role, current_parts))
                current_parts = []
            current_role = role

            if pt == "text":
                text = pd.get("text", "")
                if text.strip():
                    current_parts.append({"type": "text", "content": text})
            elif pt == "reasoning":
                text = pd.get("text", "")
                if text.strip():
                    current_parts.append({"type": "reasoning", "content": text})
            elif pt == "tool":
                st = pd.get("state", {})
                out = st.get("output", "")
                tool = pd.get("tool", "")
                title_text = st.get("title", "")
                if isinstance(out, str) and len(out) > self.MAX_TOOL_OUTPUT:
                    out = out[:self.MAX_TOOL_OUTPUT] + "\n  ...(truncated)"
                if isinstance(out, str) and out.strip():
                    current_parts.append({
                        "type": "tool",
                        "tool": tool,
                        "output": out[:self.MAX_TOOL_OUTPUT],
                        "title": str(title_text)[:200],
                    })
            elif pt == "patch":
                files = pd.get("files", [])
                if files:
                    current_parts.append({"type": "patch", "files": files})
            # step-start, step-finish, compaction, file, agent — skip

        if current_parts:
            turns.append((current_role, current_parts))

        lines: list[str] = []
        for role, parts in turns:
            if role == "user":
                lines.append("## User\n")
            elif role == "assistant":
                lines.append("## Assistant\n")
            else:
                lines.append(f"## {role}\n")

            for p in parts:
                if p["type"] == "text":
                    lines.append(p["content"].strip())
                    lines.append("")
                elif p["type"] == "reasoning":
                    lines.append("> **Reasoning:**")
                    for line in p["content"].strip().split("\n"):
                        lines.append(f"> {line}")
                    lines.append("")
                elif p["type"] == "tool":
                    lines.append(f"**`{p['tool']}`**")
                    if p.get("title"):
                        lines[-1] += f" → {p['title']}"
                    lines.append("")
                    if p.get("output"):
                        lines.append(p["output"])
                        lines.append("")
                elif p["type"] == "patch":
                    lines.append(f"**Patch:** modified {len(p['files'])} file(s):")
                    for f in p["files"]:
                        lines.append(f"  - `{f}`")
                    lines.append("")

        return "\n".join(lines)

    def get_latest_cursor(self) -> int:
        if not os.path.exists(self.source_path):
            return 0
        conn = sqlite3.connect(self.source_path)
        cur = conn.cursor()
        cur.execute("SELECT MAX(MAX(time_created, time_updated)) FROM session")
        row = cur.fetchone()
        conn.close()
        return (row[0] or 0) if row else 0
