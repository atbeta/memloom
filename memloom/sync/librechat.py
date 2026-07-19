"""LibreChat sync adapter — MongoDB → MemoryRecord (push to Hub)."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterator
from datetime import datetime

from pymongo import MongoClient

from memloom.records import MemoryRecord
from memloom.sync.adapter import SyncAdapter


class LibreChatSyncAdapter(SyncAdapter):
    """Read LibreChat conversations from a reachable MongoDB."""

    source_type = "librechat"

    def __init__(self, source_path: str, database: str = "LibreChat"):
        super().__init__(source_path)
        self._database = database
        self._client: MongoClient | None = None
        self._latest_ms = 0

    def _db(self):
        if self._client is None:
            self._client = MongoClient(self.source_path, serverSelectionTimeoutMS=5000)
        return self._client[self._database]

    def extract(self, since_ms: int | None = None) -> list[MemoryRecord]:
        db = self._db()
        conv_query: dict = {
            "isArchived": {"$ne": True},
            "isTemporary": {"$ne": True},
        }
        conversations = list(
            db.conversations.find(
                conv_query,
                {
                    "_id": 0,
                    "conversationId": 1,
                    "title": 1,
                    "user": 1,
                    "endpoint": 1,
                    "agent_id": 1,
                    "model": 1,
                    "createdAt": 1,
                    "updatedAt": 1,
                },
            )
        )

        records: list[MemoryRecord] = []
        now = int(time.time() * 1000)
        latest = since_ms or 0

        for conv in conversations:
            cid = conv.get("conversationId")
            if not cid:
                continue
            mtime = _to_ms(conv.get("updatedAt")) or _to_ms(conv.get("createdAt")) or 0
            if since_ms and mtime and mtime < since_ms:
                continue
            if mtime > latest:
                latest = mtime

            messages = list(
                db.messages.find(
                    {"conversationId": cid},
                    {
                        "_id": 0,
                        "messageId": 1,
                        "sender": 1,
                        "text": 1,
                        "createdAt": 1,
                        "model": 1,
                    },
                ).sort("createdAt", 1)
            )
            if not messages:
                continue

            title = conv.get("title") or "Untitled"
            model = conv.get("model") or "unknown"
            project = _shorten_title(title)
            emitted = 0
            for turn in _pair_into_turns(messages):
                content = _format_turn(turn)
                if not content.strip():
                    continue
                ts = _to_ms(turn[0].get("createdAt")) or mtime or now
                if since_ms and ts < since_ms:
                    continue
                if ts > latest:
                    latest = ts
                source_key = f"{cid}::{turn[0].get('messageId', emitted)}"
                records.append(
                    MemoryRecord(
                        source="librechat",
                        source_key=source_key,
                        agent=f"librechat:{model}",
                        project=project,
                        visibility="personal",
                        captured_at=now,
                        occurred_at=ts,
                        role="conversation_turn",
                        content=content,
                        raw_meta={
                            "conversation_id": cid,
                            "conversation_title": title,
                            "endpoint": conv.get("endpoint", "LibreChat"),
                            "agent_id": conv.get("agent_id") or "",
                            "model": model,
                            "user_id": conv.get("user", ""),
                        },
                    )
                )
                emitted += 1

        self._latest_ms = latest or now
        return records

    def get_latest_cursor(self) -> int:
        return self._latest_ms or int(time.time() * 1000)


def _pair_into_turns(messages: list[dict]) -> Iterator[list[dict]]:
    if not messages:
        return
    current: list[dict] = []
    for m in messages:
        sender = m.get("sender", "")
        text = (m.get("text") or "").strip()
        if not text:
            continue
        if sender == "User":
            if current:
                yield current
            current = [m]
        elif sender == "Assistant":
            if not current:
                current = [m]
            elif current[-1].get("sender") == "Assistant":
                current.append(m)
            else:
                current.append(m)
        else:
            if current:
                current.append(m)
    if current:
        yield current


def _format_turn(turn: list[dict]) -> str:
    parts: list[str] = []
    for m in turn:
        sender = m.get("sender", "")
        text = (m.get("text") or "").strip()
        if not text:
            continue
        if sender == "User":
            parts.append(f"**USER** ({_iso_short(m.get('createdAt'))}):\n{text}")
        elif sender == "Assistant":
            model = (m.get("model") or "?").split("/")[-1]
            parts.append(f"**ASSISTANT** ({model}):\n{text}")
        else:
            parts.append(f"**{sender.upper()}**:\n{text}")
    return "\n\n".join(parts)


def _shorten_title(title: str) -> str | None:
    if not title:
        return None
    return title[:50].replace(" ", "_").replace("/", "-")


def _to_ms(d) -> int | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return int(d.timestamp() * 1000)
    try:
        if isinstance(d, (int, float)):
            return int(d) if d > 1e12 else int(d * 1000)
        return int(d.timestamp() * 1000)
    except Exception:
        return None


def _iso_short(d) -> str:
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return "?"
