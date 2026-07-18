"""Project + visibility tagging.

For v0.1 we keep this minimal: project is inferred from the source's notion of
``cwd``/``workspace`` if available, otherwise left as None. visibility defaults
to "personal" — there's no company/private classification in v0.1 by design
(see MEMORY design notes).
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from ..records import MemoryRecord

# Heuristic: extract the last path component that looks like a project dir.
_PROJECT_HINT = re.compile(r"/(?:projects?|repos?|src|work)/([^/]+)/")


def tag_record(record: MemoryRecord) -> MemoryRecord:
    """Return a possibly-new record with project/visibility/tags filled."""
    if record.project:
        return record

    project = _infer_project(record)
    tags = list(record.tags)

    # Lightweight auto-tags from source/role
    tags.append(f"source:{record.source}")
    tags.append(f"role:{record.role}")
    if project:
        tags.append(f"project:{project}")

    return MemoryRecord(
        source=record.source,
        source_key=record.source_key,
        id=record.id,
        agent=record.agent,
        project=project,
        visibility=record.visibility,  # unchanged in v0.1
        captured_at=record.captured_at,
        occurred_at=record.occurred_at,
        duration_ms=record.duration_ms,
        role=record.role,
        content=record.content,
        content_hash=record.content_hash,
        raw_meta=record.raw_meta,
        raw_ref=record.raw_ref,
        tags=sorted(set(tags)),
    )


def _infer_project(record: MemoryRecord) -> str | None:
    candidates = [
        record.raw_meta.get("cwd") or "",
        record.raw_meta.get("workspace") or "",
        record.raw_meta.get("project") or "",
        record.raw_meta.get("source_path") or "",
        record.source_key,
    ]
    for c in candidates:
        if not c:
            continue
        m = _PROJECT_HINT.search(str(c))
        if m:
            return m.group(1)
    # Fallback: basename of cwd/session path
    for c in candidates[:2]:
        if c:
            return PurePosixPath(str(c)).name or None
    return None


__all__ = ["tag_record"]
