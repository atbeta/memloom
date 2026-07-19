"""Shared operational helpers used by CLI and admin API."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .embed import Embedder
from .records import MemoryRecord, RunSummary
from .store import RawStore


def run_summaries_to_dicts(summaries: list[RunSummary]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in summaries:
        out.append({
            "run_id": s.run_id,
            "source": s.source,
            "host": s.host,
            "started_at": s.started_at,
            "finished_at": s.finished_at,
            "discovered": s.discovered,
            "new_records": s.new_records,
            "duplicates": s.duplicates,
            "filtered": s.filtered,
            "errors": list(s.errors),
            "duration_ms": s.duration_ms,
        })
    return out


def embed_backfill(
    store: RawStore,
    embedder: Embedder,
    *,
    source: str | None = None,
    limit: int = 0,
    force: bool = False,
    batch_size: int = 32,
) -> dict[str, Any]:
    """Embed existing raw records into sqlite-vec. Same semantics as ``memloom embed``."""
    raw_root = Path(store.root) / "raw"
    if not raw_root.exists():
        return {"embedded": 0, "skipped": 0, "errors": []}

    files = list(raw_root.rglob("*.json"))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    embedded = 0
    skipped = 0
    errors: list[str] = []
    batch_texts: list[str] = []
    batch_ids: list[str] = []
    batch = max(1, batch_size)

    def flush() -> None:
        nonlocal embedded
        if not batch_texts:
            return
        try:
            vecs = embedder.embed_batch(batch_texts)
        except Exception as e:
            errors.append(f"batch embed failed: {e}")
            batch_texts.clear()
            batch_ids.clear()
            return
        for rid, vec in zip(batch_ids, vecs):
            try:
                store.upsert_vector(rid, vec)
                embedded += 1
            except KeyError:
                pass
            except Exception as e:
                errors.append(f"upsert_vector {rid}: {e}")
        batch_texts.clear()
        batch_ids.clear()

    for p in files:
        if limit and embedded + len(batch_texts) >= limit:
            break
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            rec = MemoryRecord.from_dict(d)
        except Exception:
            continue
        if rec.role.startswith("_"):
            continue
        if source and rec.source != source:
            continue
        if not rec.content:
            continue
        if not force:
            with store._connect(store.index_path) as c:
                rowid = store._record_rowid(c, rec.id)
                if rowid is not None:
                    exists = c.execute(
                        "SELECT 1 FROM records_vec WHERE rowid=?", (rowid,),
                    ).fetchone()
                    if exists:
                        skipped += 1
                        continue
        batch_texts.append(rec.content)
        batch_ids.append(rec.id)
        if len(batch_texts) >= batch:
            flush()
    flush()

    return {"embedded": embedded, "skipped": skipped, "errors": errors}
