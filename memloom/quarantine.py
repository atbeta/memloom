"""Quarantine: move low-value records out of the active store.

Design
------
"Quarantine" is a soft-delete-with-recovery:
  1. The raw ``.json`` and ``.md`` files are moved from ``data/raw/<source>/``
     into ``data/quarantine/<source>/``.
  2. The row in ``records`` (and the matching rows in ``records_fts`` and
     ``records_vec``) is deleted.
  3. The matching watermarks are advanced so the collector does not re-pull
     the record on the next pass.

This means: the record stops appearing in search and RAG, but the original
file is still on disk if you ever want to restore or audit it.

CLI
---
``mp quarantine list`` — show what's in quarantine
``mp quarantine add <record_id>`` — move one record
``mp quarantine add --source X --filter 'len<50'`` — bulk move by rule
``mp quarantine restore <record_id>`` — move back to active
``mp quarantine purge --older-than 30d`` — actually delete (irreversible)

Rules
-----
Default rules (configurable in the future):
  * Content length below threshold (default 30 chars)
  * Content matches a "trivial" regex (e.g. ``^\\s*(test|hello|ping|ok)\\s*[?.!]?$``)
  * Role is a synthetic marker (``_skip_marker``, ``_file_summary``)
  * Has no real conversation (only system messages)
"""
from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .records import MemoryRecord
from .store import RawStore


# Default "trivial content" patterns
DEFAULT_TRIVIAL_RE = re.compile(
    r"^\s*(test|hello|hi|hey|ping|ok(ay)?|test\s+test|1\+1|2\+2)\s*[?.!]?\s*$",
    re.IGNORECASE,
)

DEFAULT_MIN_CONTENT_LEN = 30

SYNTHETIC_ROLES = {"_skip_marker", "_file_summary"}


@dataclass
class QuarantineResult:
    """Result of a quarantine operation."""
    moved: list[str]          # list of record_ids that were moved
    skipped: list[str]        # record_ids that didn't match any rule
    not_found: list[str]      # record_ids that don't exist
    errors: list[str]         # any errors during the operation

    @property
    def total(self) -> int:
        return len(self.moved) + len(self.skipped) + len(self.not_found)


def list_quarantined(store: RawStore) -> list[dict]:
    """List everything in data/quarantine/.

    Returns one entry per quarantined record with its metadata (recovered from
    the original .json file).
    """
    quar_dir = Path(store.root) / "quarantine"
    if not quar_dir.exists():
        return []
    out: list[dict] = []
    for src_dir in sorted(quar_dir.iterdir()):
        if not src_dir.is_dir():
            continue
        for f in sorted(src_dir.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append({
                "id": d.get("id"),
                "source": d.get("source"),
                "source_key": d.get("source_key"),
                "role": d.get("role"),
                "captured_at": d.get("captured_at"),
                "path": str(f),
            })
    return out


def _matches_rule(
    rec: MemoryRecord,
    min_len: int = DEFAULT_MIN_CONTENT_LEN,
    trivial_re: re.Pattern = DEFAULT_TRIVIAL_RE,
) -> tuple[bool, str]:
    """Return (matches, reason) if the record should be quarantined."""
    if rec.role in SYNTHETIC_ROLES:
        return True, f"synthetic role ({rec.role})"
    content = (rec.content or "").strip()
    if len(content) < min_len:
        return True, f"too short ({len(content)} chars < {min_len})"
    if trivial_re.match(content):
        return True, f"trivial content (matched {trivial_re.pattern!r})"
    # Heuristic: a conversation_turn with NEITHER USER nor ASSISTANT marker
    # is broken (parser failed). A turn with only one of the two is fine
    # (e.g. multi-turn continuation where the user message is in a previous
    # record, or a single-shot question with no follow-up).
    if rec.role == "conversation_turn":
        has_user = "**USER**" in (rec.content or "")
        has_assistant = "**ASSISTANT**" in (rec.content or "")
        if not has_user and not has_assistant:
            return True, "conversation_turn with no USER or ASSISTANT marker"
    return False, ""


def find_quarantine_candidates(
    store: RawStore,
    sources: list[str] | None = None,
    min_len: int = DEFAULT_MIN_CONTENT_LEN,
    trivial_re: re.Pattern = DEFAULT_TRIVIAL_RE,
) -> Iterator[tuple[MemoryRecord, str]]:
    """Yield (record, reason) for every record that matches the quarantine rules."""
    for rec in _iter_all_records(store, sources=sources):
        matches, reason = _matches_rule(rec, min_len=min_len, trivial_re=trivial_re)
        if matches:
            yield rec, reason


def _iter_all_records(
    store: RawStore, sources: list[str] | None = None
) -> Iterator[MemoryRecord]:
    """Yield every record by reading the raw/ JSON files."""
    raw_dir = Path(store.root) / "raw"
    if not raw_dir.exists():
        return
    for src_dir in raw_dir.iterdir():
        if not src_dir.is_dir():
            continue
        if sources and src_dir.name not in sources:
            continue
        for f in src_dir.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                rec = MemoryRecord.from_dict(d)
            except Exception:
                continue
            yield rec


def move_to_quarantine(
    store: RawStore,
    record_ids: list[str],
    reason: str = "manual",
) -> QuarantineResult:
    """Move records to the quarantine directory.

    For each record:
      * Move ``raw/<source>/<key>.json`` and ``.md`` → ``quarantine/<source>/``
      * Delete row from ``records`` (cascade removes FTS5 + vec via SQL)
      * Update watermark so collector won't re-pull

    Returns a :class:`QuarantineResult` with per-id outcomes.
    """
    result = QuarantineResult(moved=[], skipped=[], not_found=[], errors=[])
    raw_dir = Path(store.root) / "raw"
    quar_dir = Path(store.root) / "quarantine"
    quar_dir.mkdir(parents=True, exist_ok=True)

    for rid in record_ids:
        try:
            # Find the record (rowid + json_path)
            with store._connect(store.index_path) as c:
                row = c.execute(
                    "SELECT source, source_key, json_path, md_path, rowid "
                    "FROM records WHERE id=?", (rid,)
                ).fetchone()
                if not row:
                    result.not_found.append(rid)
                    continue
                source, source_key, json_path, md_path, rowid = row
                src_dir_name = store._safe_name(source)
                quar_src_dir = quar_dir / src_dir_name
                quar_src_dir.mkdir(parents=True, exist_ok=True)
                safe_key = store._safe_name(source_key)
                target_json = quar_src_dir / f"{safe_key}.json"
                target_md = quar_src_dir / f"{safe_key}.md"
                # Move files
                moved_any = False
                json_p = Path(json_path) if json_path else None
                md_p = Path(md_path) if md_path else None
                if json_p and json_p.exists():
                    shutil.move(str(json_p), str(target_json))
                    moved_any = True
                if md_p and md_p.exists():
                    shutil.move(str(md_p), str(target_md))
                if not moved_any:
                    result.errors.append(f"{rid}: no source files found")
                    continue
                # Delete from indexes
                c.execute("DELETE FROM records WHERE id=?", (rid,))
                c.execute("DELETE FROM records_fts WHERE id=?", (rid,))
                if rowid is not None:
                    c.execute("DELETE FROM records_vec WHERE rowid=?", (rowid,))
                # Stamp reason in a sidecar file (optional metadata)
                (quar_src_dir / f"{safe_key}.quarantine.json").write_text(
                    json.dumps({
                        "id": rid,
                        "reason": reason,
                        "quarantined_at": _now_ms(),
                    }, ensure_ascii=False),
                    encoding="utf-8",
                )
            # Update watermark so the collector won't re-pull this record.
            # Use source + source_key as the watermark key.
            from .records import Watermark
            wm = Watermark(
                source=source,
                source_key=source_key,
                last_seen_ms=0,  # treat as "no new content" for this source_key
                last_hash="",
                last_run_id="quarantine",
            )
            store.upsert_watermark(wm)
            result.moved.append(rid)
        except Exception as e:
            result.errors.append(f"{rid}: {e}")
    return result


def restore_from_quarantine(
    store: RawStore, record_ids: list[str]
) -> dict:
    """Move records back from quarantine to raw/. Returns counts."""
    moved: list[str] = []
    not_found: list[str] = []
    errors: list[str] = []
    raw_dir = Path(store.root) / "raw"
    quar_dir = Path(store.root) / "quarantine"

    for rid in record_ids:
        # Find the file
        found = None
        for src_dir in quar_dir.iterdir():
            if not src_dir.is_dir():
                continue
            for f in src_dir.glob("*.json"):
                if not f.name.endswith(".quarantine.json"):
                    try:
                        d = json.loads(f.read_text(encoding="utf-8"))
                        if d.get("id") == rid:
                            found = (src_dir, f)
                            break
                    except: pass
            if found: break
        if not found:
            not_found.append(rid)
            continue
        src_dir, json_file = found
        # Source is recovered from the parent dir
        source = src_dir.name
        target_src_dir = raw_dir / source
        target_src_dir.mkdir(parents=True, exist_ok=True)
        safe_key = json_file.stem
        target_json = target_src_dir / f"{safe_key}.json"
        target_md = target_src_dir / f"{safe_key}.md"
        sidecar = src_dir / f"{safe_key}.quarantine.json"
        try:
            shutil.move(str(json_file), str(target_json))
            md_file = src_dir / f"{safe_key}.md"
            if md_file.exists():
                shutil.move(str(md_file), str(target_md))
            if sidecar.exists():
                sidecar.unlink()
            # Re-index: read the JSON, upsert into store (idempotent)
            try:
                rec = MemoryRecord.from_dict(
                    json.loads(target_json.read_text(encoding="utf-8"))
                )
                store.upsert(rec)
            except Exception as e:
                errors.append(f"{rid}: re-index failed ({e})")
            moved.append(rid)
        except Exception as e:
            errors.append(f"{rid}: {e}")
    return {"moved": moved, "not_found": not_found, "errors": errors}


def _now_ms() -> int:
    import time
    return int(time.time() * 1000)


__all__ = [
    "QuarantineResult",
    "list_quarantined",
    "find_quarantine_candidates",
    "move_to_quarantine",
    "restore_from_quarantine",
    "DEFAULT_TRIVIAL_RE",
    "DEFAULT_MIN_CONTENT_LEN",
]