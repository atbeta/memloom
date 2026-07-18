"""OpenClaw collector.

Sources:
  * ``MEMORY.md``            — long-term curated memory
  * ``memory/YYYY-MM-DD.md`` — daily notes
  * ``SOUL.md`` / ``USER.md`` — agent identity files (low-priority)

Each .md file → one MemoryRecord. Whole file content. We don't split into
chunks here — chunking is a retrieval-time concern, not a collection concern.

Configuration:
  Set ``workspace`` in agent options to point at the OpenClaw workspace root.
  Example::

    - type: openclaw
      host: local
      options:
        workspace: /home/node/.openclaw/workspace
"""
from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

from ..records import MemoryRecord, Source, Watermark
from ..transport.base import Transport
from .base import AgentAdapter, CollectorContext

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
_DREAM_DIR = "memory/dreaming"


class OpenClawAdapter(AgentAdapter):
    name = "openclaw"

    # Default file basenames, resolved relative to the workspace root.
    _DEFAULT_FILES = [
        "MEMORY.md",
        "SOUL.md",
        "USER.md",
        "IDENTITY.md",
        "AGENTS.md",
    ]
    _DEFAULT_DAILY_GLOB = "memory/*.md"
    _DEFAULT_EXCLUDE = {"memory/dreaming"}

    def __init__(self, options: dict | None = None) -> None:
        super().__init__(options)
        opts = options or {}
        # workspace can come from options OR be guessed
        ws = opts.get("workspace") or os.environ.get("OPENCLAW_WORKSPACE")
        if ws:
            self._workspace = Path(ws).expanduser().resolve()
        else:
            self._workspace = self._guess_workspace()

    def _guess_workspace(self) -> Path | None:
        """Best-effort default: look for ~/.openclaw/workspace first, then $HOME."""
        candidates = [
            Path("~/.openclaw/workspace").expanduser(),
            Path.home(),
        ]
        for c in candidates:
            if (c / "MEMORY.md").exists():
                return c.resolve()
        return None

    # ---- Discover ----

    def discover(self, transport: Transport) -> list[Source]:
        if self._workspace is None:
            return []
        sources: list[Source] = []

        # Top-level files
        for fname in self._DEFAULT_FILES:
            p = self._workspace / fname
            if p.exists():
                sources.append(Source(
                    source=self.name,
                    host="?",   # filled in by runner
                    transport=transport.name,
                    path=str(p),
                ))

        # Daily notes
        daily_dir = self._workspace / "memory"
        if daily_dir.is_dir():
            for p in sorted(daily_dir.glob("*.md")):
                rel = p.relative_to(self._workspace).as_posix()
                if rel in self._DEFAULT_EXCLUDE:
                    continue
                # Skip subdirs (e.g. memory/dreaming/)
                if p.is_dir():
                    continue
                sources.append(Source(
                    source=self.name,
                    host="?",
                    transport=transport.name,
                    path=str(p),
                ))

        return sources

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

        text = ctx.transport.read_text(source.path)
        h = _content_hash(text)

        # Skip if content hash unchanged
        if last_wm and last_wm.last_hash == h:
            yield self._build_skip_watermark(source, stat.mtime_ms, h, ctx.run_id)
            return

        # Classify role + project
        role, project = self._classify(source.path)

        rec = MemoryRecord(
            source=self.name,
            source_key=source.path,
            agent="openclaw",
            project=project,
            visibility="personal",
            captured_at=self.now_ms(),
            occurred_at=stat.mtime_ms,
            role=role,
            content=text,
            raw_meta={
                "workspace": str(self._workspace) if self._workspace else None,
                "size_bytes": stat.size,
                "mtime_ms": stat.mtime_ms,
            },
        )

        yield rec, Watermark(
            source=self.name,
            source_key=source.path,
            last_seen_ms=stat.mtime_ms,
            last_hash=h,
            last_run_id=ctx.run_id,
        )

    # ---- Helpers ----

    def _classify(self, path: str) -> tuple[str, str | None]:
        name = PurePosixPath(path).name
        m = _DATE_RE.match(name)
        if m:
            return "daily_note", m.group(1)
        if name == "MEMORY.md":
            return "long_term_memory", None
        if name == "SOUL.md":
            return "soul", None
        if name == "USER.md":
            return "user_profile", None
        if name == "IDENTITY.md":
            return "identity", None
        if name == "AGENTS.md":
            return "workspace_config", None
        return "note", None

    def _build_skip_watermark(self, source: Source, mtime_ms: int, h: str, run_id: str) -> tuple[MemoryRecord, Watermark]:
        rec = MemoryRecord(
            source=self.name,
            source_key=source.path,
            agent="openclaw",
            role="_skip_marker",
            content="",
            content_hash=h,
            captured_at=self.now_ms(),
            occurred_at=mtime_ms,
        )
        return rec, Watermark(
            source=self.name,
            source_key=source.path,
            last_seen_ms=mtime_ms,
            last_hash=h,
            last_run_id=run_id,
        )


def _content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = ["OpenClawAdapter"]
