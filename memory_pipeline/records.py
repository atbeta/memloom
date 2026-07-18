"""Core data types: MemoryRecord and Watermark.

MemoryRecord is the *immutable* contract between collectors and the rest of the
pipeline. Collectors produce these; the pipeline never mutates them. Watermark
is how collectors track incremental progress.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# ---------- Identifier & hashing helpers ---------------------------------

def record_id(source: str, source_key: str) -> str:
    """Stable, deterministic record id from (source, source_key).

    Using sha256 instead of uuid so re-runs are idempotent.
    """
    h = hashlib.sha256(f"{source}::{source_key}".encode()).hexdigest()
    return f"rec_{h[:24]}"


def content_hash(content: str) -> str:
    """Stable content fingerprint (for dedup)."""
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


# ---------- Visibility ----------------------------------------------------

Visibility = Literal["personal", "company", "mixed", "public", "unknown"]


# ---------- MemoryRecord --------------------------------------------------

@dataclass
class MemoryRecord:
    """A single memory entry from any source, in a unified shape.

    Collectors MUST output these. Downstream pipeline (privacy/dedup/tag/store)
    consumes them. The shape is a contract — adding a new optional field is OK,
    but renaming/removing is breaking.
    """

    # ---- Identity ----
    source: str               # "openclaw" | "claude_code" | "codex" | ...
    source_key: str           # source-local key (file path, db row id, message id)
    id: str = ""              # auto-filled by __post_init__: rec_<sha256>

    # ---- Provenance ----
    agent: str = ""           # which agent generated it (for agent-attributed entries)
    project: str | None = None  # detected project, if any
    visibility: Visibility = "personal"

    # ---- Timing ----
    captured_at: int = 0      # ms epoch — when the *collector* saw it
    occurred_at: int | None = None  # ms epoch — when the event originally happened
    duration_ms: int | None = None

    # ---- Content ----
    role: str = "note"        # "user" | "assistant" | "tool" | "system" | "note" | "summary" | ...
    content: str = ""
    content_hash: str = ""    # auto-filled by __post_init__: sha256:...

    # ---- Metadata (free-form, source-specific, kept as-is) ----
    raw_meta: dict[str, Any] = field(default_factory=dict)

    # ---- Reference back to raw ----
    raw_ref: str | None = None  # relative path under data_root/raw/, e.g. "openclaw/2026-07-18.md"

    # ---- Tags (filled by pipeline/tag.py) ----
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = record_id(self.source, self.source_key)
        if self.content and not self.content_hash:
            self.content_hash = content_hash(self.content)
        if self.captured_at == 0:
            self.captured_at = int(time.time() * 1000)

    # ---- Serialization ----

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MemoryRecord:
        # Defensive: ignore unknown keys so future schema additions don't crash old code.
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def from_json(cls, s: str) -> MemoryRecord:
        return cls.from_dict(json.loads(s))

    # ---- Markdown rendering (for raw/<source>/<id>.md) ----

    def to_markdown(self) -> str:
        lines = [
            f"# {self.id}",
            "",
            f"- **source**: `{self.source}`",
            f"- **source_key**: `{self.source_key}`",
            f"- **agent**: `{self.agent}`" if self.agent else "- **agent**: _(none)_",
            f"- **project**: `{self.project}`" if self.project else "- **project**: _(none)_",
            f"- **visibility**: {self.visibility}",
            f"- **role**: {self.role}",
            f"- **captured_at**: {self.captured_at} ({_fmt_ts(self.captured_at)})",
        ]
        if self.occurred_at:
            lines.append(f"- **occurred_at**: {self.occurred_at} ({_fmt_ts(self.occurred_at)})")
        if self.raw_meta:
            lines.append("- **raw_meta**:")
            lines.append("")
            lines.append("  ```json")
            lines.append("  " + json.dumps(self.raw_meta, ensure_ascii=False, indent=2).replace("\n", "\n  "))
            lines.append("  ```")
        if self.tags:
            lines.append(f"- **tags**: {', '.join(f'`{t}`' for t in self.tags)}")
        if self.raw_ref:
            lines.append(f"- **raw_ref**: `{self.raw_ref}`")
        lines += ["", "---", "", "## Content", "", self.content or "_(empty)_", ""]
        return "\n".join(lines)


def _fmt_ts(ms: int) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ms / 1000, tz=_dt.UTC).isoformat(timespec="seconds")


# ---------- Watermark -----------------------------------------------------

# Different sources track progress differently. The pipeline hands collectors a
# watermark; collectors persist it; on next run the collector decides what's new.

@dataclass
class Watermark:
    """Incremental cursor for a single source path.

    The collector may store any of these in its own format; pipeline only cares
    about (source, source_key) → watermark mapping for re-pull safety.
    """
    source: str
    source_key: str           # file path / db row id / url
    last_seen_ms: int = 0     # mtime or occurred_at of last consumed item
    last_hash: str = ""       # optional — content hash, for change-without-mtime
    last_run_id: str = ""     # UUID of the collector run that produced this

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Watermark:
        return cls(**d)


# ---------- Source descriptor --------------------------------------------

@dataclass
class Source:
    """A specific thing to collect from (a file, a directory, a DB table)."""
    source: str
    host: str                 # "local" | "gpu-103" | etc — must match transport host
    path: str                 # human-readable: file path, db path, glob pattern
    transport: str = "local"  # "local" | "ssh"
    extra: dict[str, Any] = field(default_factory=dict)
    source_key: str = ""      # auto = path if empty

    def __post_init__(self) -> None:
        if not self.source_key:
            self.source_key = self.path


# ---------- Run summary ---------------------------------------------------

@dataclass
class RunSummary:
    """One collector run's outcome, written to index.sqlite for visibility."""
    run_id: str = field(default_factory=lambda: f"run_{uuid.uuid4().hex[:16]}")
    started_at: int = field(default_factory=lambda: int(time.time() * 1000))
    finished_at: int = 0
    source: str = ""
    host: str = ""
    discovered: int = 0
    new_records: int = 0
    duplicates: int = 0
    filtered: int = 0
    errors: list[str] = field(default_factory=list)

    def finish(self) -> None:
        self.finished_at = int(time.time() * 1000)

    @property
    def duration_ms(self) -> int:
        if not self.finished_at:
            return 0
        return self.finished_at - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "MemoryRecord",
    "Watermark",
    "Source",
    "RunSummary",
    "Visibility",
    "record_id",
    "content_hash",
]
