"""LibreChat collector.

Reads conversations and messages from LibreChat's MongoDB and emits one
``MemoryRecord`` per conversation turn (one user message + the following
assistant response).

MongoDB schema (LibreChat v1.x)
--------------------------------

``conversations`` collection: metadata for each chat session.

    {
      "conversationId": "uuid",
      "title": "Electron Open Issues Summary",
      "user": "user-id",
      "endpoint": "LibreChat" | "agents",
      "endpointType": "...",
      "agent_id": "..." | null,
      "model": "hub-chat-fast" | null,
      "messages": [ObjectId, ObjectId, ...]   # just IDs, not actual data
      "createdAt": ISODate,
      "updatedAt": ISODate,
      "tags": [...],
      "files": [...],
    }

``messages`` collection: actual message data (must be joined by conversationId).

    {
      "messageId": "uuid",
      "conversationId": "uuid",
      "sender": "User" | "Assistant",
      "text": "...",
      "createdAt": ISODate,
      "model": "..." | null,
      "tokenCount": int,
    }

Pairing strategy
----------------

Messages within a conversation are grouped into turns:
  * If a ``User`` message is followed by one or more ``Assistant`` messages
    before the next ``User``, the first Assistant response is paired with
    the user message → one turn = one MemoryRecord.
  * Consecutive ``User`` messages (e.g. multi-part question) get separate
    turns.
  * Consecutive ``Assistant`` messages (tool calls, continuations) collapse
    into the previous turn.
  * Standalone ``Assistant`` messages without a preceding user get their
    own turn (multi-turn continuation).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import PurePosixPath
from typing import Iterator

from pymongo import MongoClient

from ..records import MemoryRecord, Source, Watermark
from ..transport.base import Transport
from .base import AgentAdapter, CollectorContext


class LibreChatAdapter(AgentAdapter):
    name = "librechat"
    default_paths = []  # not filesystem-based; uses MongoDB

    def __init__(self, options: dict | None = None) -> None:
        super().__init__(options)
        opts = options or {}
        import os
        self._mongo_uri = (
            opts.get("mongo_uri")
            or os.environ.get("MEMLOOM_LIBRECHAT_MONGO_URI")
            or "mongodb://librechat-mongodb:27017/"
        )
        self._database = opts.get("database", "LibreChat")
        self._client: MongoClient | None = None
        self._conversations_cache: dict[str, dict] | None = None

    # ---- connection management ----

    def _db(self):
        if self._client is None:
            self._client = MongoClient(self._mongo_uri, serverSelectionTimeoutMS=5000)
        return self._client[self._database]

    def _load_conversations(self) -> dict[str, dict]:
        """Return mapping conversationId → conversation doc (cached per pull)."""
        if self._conversations_cache is not None:
            return self._conversations_cache
        db = self._db()
        self._conversations_cache = {
            c["conversationId"]: c
            for c in db.conversations.find({}, {
                "_id": 0,
                "conversationId": 1,
                "title": 1,
                "user": 1,
                "endpoint": 1,
                "endpointType": 1,
                "agent_id": 1,
                "model": 1,
                "createdAt": 1,
                "updatedAt": 1,
                "tags": 1,
                "isArchived": 1,
                "isTemporary": 1,
            })
        }
        return self._conversations_cache

    def _invalidate_cache(self) -> None:
        self._conversations_cache = None

    # ---- Discover ----

    def discover(self, transport: Transport) -> list[Source]:
        convs = self._load_conversations()
        out: list[Source] = []
        for cid, conv in convs.items():
            # Skip archived / temporary unless explicitly requested
            if conv.get("isArchived") or conv.get("isTemporary"):
                continue
            out.append(Source(
                source=self.name,
                host="?",
                transport="mongodb",  # not really a transport — informational
                path=f"mongodb://{self._database}/conversations/{cid}",
            ))
        return out

    # ---- Pull ----

    def pull(
        self,
        source: Source,
        ctx: CollectorContext,
    ) -> Iterator[tuple[MemoryRecord, Watermark]]:
        # conversationId is stored in the Source.path we set above
        cid = source.path.rsplit("/", 1)[-1]
        convs = self._load_conversations()
        conv = convs.get(cid)
        if not conv:
            return

        last_wm = ctx.last_watermarks.get(source.source_key)
        if last_wm and last_wm.last_seen_ms >= self._conv_mtime_ms(conv):
            return

        # Fetch all messages for this conversation, sorted by time
        db = self._db()
        cursor = db.messages.find(
            {"conversationId": cid},
            {"_id": 0, "messageId": 1, "sender": 1, "text": 1,
             "createdAt": 1, "model": 1, "tokenCount": 1,
             "isCreatedByUser": 1, "parentMessageId": 1},
        ).sort("createdAt", 1)

        messages = list(cursor)
        if not messages:
            return

        # Pair into turns
        title = conv.get("title") or "Untitled"
        endpoint = conv.get("endpoint", "LibreChat")
        model = conv.get("model") or "unknown"
        user_id = conv.get("user", "")
        agent_id = conv.get("agent_id") or ""
        conv_created = conv.get("createdAt")
        conv_updated = conv.get("updatedAt")
        project = _shorten_title(title)

        emitted = 0
        for turn in _pair_into_turns(messages):
            content = _format_turn(turn)
            if not content.strip():
                continue
            ts = _to_ms(turn[0].get("createdAt")) or _to_ms(conv_created) or self.now_ms()
            source_key = f"{cid}::{turn[0].get('messageId', emitted)}"
            rec = MemoryRecord(
                source=self.name,
                source_key=source_key,
                agent=f"librechat:{model}",
                project=project,
                visibility="personal",
                captured_at=self.now_ms(),
                occurred_at=ts,
                role="conversation_turn",
                content=content,
                raw_meta={
                    "conversation_id": cid,
                    "conversation_title": title,
                    "endpoint": endpoint,
                    "agent_id": agent_id,
                    "model": model,
                    "user_id": user_id,
                    "turn_message_ids": [m.get("messageId") for m in turn],
                    "turn_senders": [m.get("sender") for m in turn],
                    "conversation_created_at": _iso(conv_created),
                    "conversation_updated_at": _iso(conv_updated),
                },
            )
            emitted += 1
            yield rec, Watermark(
                source=self.name,
                source_key=source.path,   # file-level watermark
                last_seen_ms=self._conv_mtime_ms(conv),
                last_hash=_content_hash(content),
                last_run_id=ctx.run_id,
            )

        if emitted == 0:
            yield MemoryRecord(
                source=self.name,
                source_key=source.path,
                agent="librechat",
                role="_skip_marker",
                content="",
                content_hash="",
                captured_at=self.now_ms(),
                occurred_at=self.now_ms(),
            ), Watermark(
                source=self.name,
                source_key=source.path,
                last_seen_ms=self._conv_mtime_ms(conv),
                last_hash="",
                last_run_id=ctx.run_id,
            )

    # ---- helpers ----

    def _conv_mtime_ms(self, conv: dict) -> int:
        return _to_ms(conv.get("updatedAt")) or _to_ms(conv.get("createdAt")) or 0


# ---------- pairing / formatting ----------

def _pair_into_turns(messages: list[dict]) -> Iterator[list[dict]]:
    """Yield lists of messages, each list = one turn.

    Rule: a turn starts with a User message and includes all following
    Assistant messages until the next User. A standalone Assistant
    (no preceding User in this conversation) also gets its own turn.
    """
    if not messages:
        return
    current: list[dict] = []
    prev_sender = None
    for m in messages:
        sender = m.get("sender", "")
        text = (m.get("text") or "").strip()
        if not text:
            continue
        if sender == "User":
            # Flush previous turn (if any)
            if current:
                yield current
            current = [m]
        elif sender == "Assistant":
            if not current:
                # Standalone Assistant (multi-turn continuation)
                current = [m]
            elif current[-1].get("sender") == "Assistant":
                # Continuation of assistant (e.g. tool use + final answer)
                current.append(m)
            else:
                # Normal case: previous was User → pair them
                current.append(m)
        else:
            # Tool / system message: attach to current turn if any
            if current:
                current.append(m)
            # else: drop
        prev_sender = sender
    if current:
        yield current


def _format_turn(turn: list[dict]) -> str:
    """Render a turn as markdown, **USER**: / **ASSISTANT**: format."""
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


def _shorten_title(title: str) -> str:
    """Return a project label from the conversation title (truncated)."""
    if not title:
        return None
    return title[:50].replace(" ", "_").replace("/", "-")


def _to_ms(d) -> int | None:
    """Mongo ISODate / datetime / None → epoch milliseconds."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return int(d.timestamp() * 1000)
    try:
        # Some drivers return ms directly
        if isinstance(d, (int, float)):
            return int(d) if d > 1e12 else int(d * 1000)
        return int(d.timestamp() * 1000)
    except Exception:
        return None


def _iso(d) -> str | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.isoformat()
    return str(d)


def _iso_short(d) -> str:
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return "?"


def _content_hash(text: str) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = ["LibreChatAdapter"]