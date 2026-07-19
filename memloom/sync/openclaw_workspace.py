"""OpenClaw workspace markdown sync adapter (MEMORY.md, daily notes, etc.)."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path, PurePosixPath

from memloom.records import MemoryRecord
from memloom.sync.adapter import SyncAdapter

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
_DEFAULT_FILES = [
    "MEMORY.md",
    "SOUL.md",
    "USER.md",
    "IDENTITY.md",
    "AGENTS.md",
]


class OpenClawWorkspaceAdapter(SyncAdapter):
    source_type = "openclaw"

    def __init__(self, source_path: str):
        super().__init__(source_path)
        self._latest_ms = 0

    def extract(self, since_ms: int | None = None) -> list[MemoryRecord]:
        root = Path(self.source_path).expanduser()
        if not root.is_dir():
            return []

        paths: list[Path] = []
        for fname in _DEFAULT_FILES:
            p = root / fname
            if p.is_file():
                paths.append(p)
        daily = root / "memory"
        if daily.is_dir():
            for p in sorted(daily.glob("*.md")):
                if p.is_file():
                    paths.append(p)

        now = int(time.time() * 1000)
        records: list[MemoryRecord] = []
        latest = since_ms or 0

        for p in paths:
            try:
                mtime_ms = int(p.stat().st_mtime * 1000)
            except OSError:
                continue
            if since_ms and mtime_ms < since_ms:
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            if not text.strip():
                continue
            if mtime_ms > latest:
                latest = mtime_ms
            role, project = _classify(p, root)
            records.append(
                MemoryRecord(
                    source="openclaw",
                    source_key=str(p),
                    agent="openclaw",
                    project=project,
                    visibility="personal",
                    captured_at=now,
                    occurred_at=mtime_ms,
                    role=role,
                    content=text,
                    raw_meta={
                        "workspace": str(root),
                        "mtime_ms": mtime_ms,
                        "content_hash": "sha256:"
                        + hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    },
                )
            )

        self._latest_ms = latest or now
        return records

    def get_latest_cursor(self) -> int:
        return self._latest_ms or int(time.time() * 1000)


def _classify(path: Path, root: Path) -> tuple[str, str | None]:
    try:
        name = path.relative_to(root).as_posix()
    except ValueError:
        name = path.name
    base = PurePosixPath(name).name
    m = _DATE_RE.match(base)
    if m:
        return "daily_note", m.group(1)
    if base == "MEMORY.md":
        return "long_term_memory", None
    if base == "SOUL.md":
        return "soul", None
    if base == "USER.md":
        return "user_profile", None
    if base == "IDENTITY.md":
        return "identity", None
    if base == "AGENTS.md":
        return "workspace_config", None
    return "note", None
