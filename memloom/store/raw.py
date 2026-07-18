"""Raw store: writes records to disk in three forms + a SQLite FTS5 index.

Layout under ``data_root``::

    data_root/
      raw/
        <source>/
          <source_key_basename>.json    # full structured record
          <source_key_basename>.md      # human-readable mirror
          attachments/                  # optional binary blobs (images, etc.)
      index.sqlite                      # metadata + FTS5 over content
      runs.sqlite                       # run history
      watermarks.json                   # per-source incremental cursors

Three writes per record:
  1. ``raw/<source>/<key>.json`` — full MemoryRecord (canonical)
  2. ``raw/<source>/<key>.md``   — markdown view (grep/browse friendly)
  3. ``index.sqlite``            — row + FTS5 entry for retrieval

Idempotency: writes are keyed by record.id; re-writing the same record is a
no-op. Collectors can re-run freely.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..records import MemoryRecord, RunSummary, Watermark

# ---------- Schema ----------

_INDEX_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
  id              TEXT PRIMARY KEY,
  source          TEXT NOT NULL,
  source_key      TEXT NOT NULL,
  agent           TEXT,
  project         TEXT,
  visibility      TEXT,
  role            TEXT,
  captured_at     INTEGER NOT NULL,
  occurred_at     INTEGER,
  content_hash    TEXT,
  raw_ref         TEXT,
  json_path       TEXT NOT NULL,
  md_path         TEXT NOT NULL,
  created_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_source      ON records(source);
CREATE INDEX IF NOT EXISTS idx_records_project     ON records(project);
CREATE INDEX IF NOT EXISTS idx_records_occurred_at ON records(occurred_at);
CREATE INDEX IF NOT EXISTS idx_records_captured_at ON records(captured_at);

CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
  id UNINDEXED,
  source,
  agent,
  project,
  role,
  content,
  tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS runs (
  run_id        TEXT PRIMARY KEY,
  source        TEXT,
  host          TEXT,
  started_at    INTEGER,
  finished_at   INTEGER,
  discovered    INTEGER,
  new_records   INTEGER,
  duplicates    INTEGER,
  filtered      INTEGER,
  errors_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);
"""

_WATERMARKS_FILENAME = "watermarks.json"
_INDEX_FILENAME = "index.sqlite"
_RUNS_FILENAME = "runs.sqlite"


# ---------- Store ----------

class RawStore:
    """Thread-safe raw store backed by SQLite + filesystem."""

    def __init__(self, data_root: str | Path) -> None:
        self.root = Path(data_root).expanduser().resolve()
        self.raw_dir = self.root / "raw"
        self.index_path = self.root / _INDEX_FILENAME
        self.runs_path = self.root / _RUNS_FILENAME
        self.watermarks_path = self.root / _WATERMARKS_FILENAME
        for d in [self.raw_dir]:
            d.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._connect(self.index_path) as c:
            c.executescript(_INDEX_SCHEMA)
        with self._connect(self.runs_path) as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                  run_id        TEXT PRIMARY KEY,
                  source        TEXT,
                  host          TEXT,
                  started_at    INTEGER,
                  finished_at   INTEGER,
                  discovered    INTEGER,
                  new_records   INTEGER,
                  duplicates    INTEGER,
                  filtered      INTEGER,
                  errors_json   TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);
                """
            )

    @contextmanager
    def _connect(self, path: Path) -> Iterator[sqlite3.Connection]:
        with self._lock:
            c = sqlite3.connect(str(path), timeout=30)
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            try:
                yield c
                c.commit()
            finally:
                c.close()

    # ---- Record I/O ----

    def _key_to_paths(self, source: str, source_key: str) -> tuple[Path, Path]:
        """Map (source, source_key) to safe filesystem paths."""
        safe = self._safe_name(source_key)
        d = self.raw_dir / self._safe_name(source)
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{safe}.json", d / f"{safe}.md"

    @staticmethod
    def _safe_name(s: str) -> str:
        """Replace path separators and unsafe chars so source_key becomes a filename."""
        keep = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        out = []
        for ch in s:
            out.append(ch if ch in keep else "_")
        return "".join(out).strip("_") or "unnamed"

    def has(self, record_id: str) -> bool:
        with self._connect(self.index_path) as c:
            row = c.execute("SELECT 1 FROM records WHERE id=?", (record_id,)).fetchone()
            return row is not None

    def upsert(self, record: MemoryRecord) -> bool:
        """Write record to disk + index. Returns True if newly inserted, False if existing."""
        json_path, md_path = self._key_to_paths(record.source, record.source_key)
        raw_ref = str(json_path.relative_to(self.root))

        # Always (re)write files so content updates are reflected.
        json_path.write_text(record.to_json(), encoding="utf-8")
        md_path.write_text(record.to_markdown(), encoding="utf-8")

        with self._connect(self.index_path) as c:
            existing = c.execute("SELECT 1 FROM records WHERE id=?", (record.id,)).fetchone()
            if existing:
                # Update in place (id, source, source_key stay)
                c.execute(
                    """UPDATE records SET
                        agent=?, project=?, visibility=?, role=?,
                        captured_at=?, occurred_at=?, content_hash=?,
                        raw_ref=?, json_path=?, md_path=?
                       WHERE id=?""",
                    (
                        record.agent or None,
                        record.project,
                        record.visibility,
                        record.role,
                        record.captured_at,
                        record.occurred_at,
                        record.content_hash,
                        raw_ref,
                        str(json_path),
                        str(md_path),
                        record.id,
                    ),
                )
                c.execute("DELETE FROM records_fts WHERE id=?", (record.id,))
                c.execute(
                    "INSERT INTO records_fts(id, source, agent, project, role, content) VALUES (?,?,?,?,?,?)",
                    (
                        record.id, record.source, record.agent, record.project or "",
                        record.role, record.content,
                    ),
                )
                return False

            c.execute(
                """INSERT INTO records(id, source, source_key, agent, project,
                                       visibility, role, captured_at, occurred_at,
                                       content_hash, raw_ref, json_path, md_path, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.id, record.source, record.source_key, record.agent,
                    record.project, record.visibility, record.role,
                    record.captured_at, record.occurred_at,
                    record.content_hash, raw_ref, str(json_path), str(md_path),
                    int(time.time() * 1000),
                ),
            )
            c.execute(
                "INSERT INTO records_fts(id, source, agent, project, role, content) VALUES (?,?,?,?,?,?)",
                (
                    record.id, record.source, record.agent, record.project or "",
                    record.role, record.content,
                ),
            )
            return True

    # ---- Run history ----

    def record_run(self, summary: RunSummary) -> None:
        with self._connect(self.runs_path) as c:
            c.execute(
                """INSERT OR REPLACE INTO runs
                   (run_id, source, host, started_at, finished_at,
                    discovered, new_records, duplicates, filtered, errors_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    summary.run_id, summary.source, summary.host,
                    summary.started_at, summary.finished_at,
                    summary.discovered, summary.new_records,
                    summary.duplicates, summary.filtered,
                    json.dumps(summary.errors),
                ),
            )

    def recent_runs(self, limit: int = 20) -> list[dict]:
        with self._connect(self.runs_path) as c:
            rows = c.execute(
                "SELECT run_id, source, host, started_at, finished_at, "
                "discovered, new_records, duplicates, filtered, errors_json "
                "FROM runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            errs = json.loads(r[9]) if r[9] else []
            out.append({
                "run_id": r[0], "source": r[1], "host": r[2],
                "started_at": r[3], "finished_at": r[4],
                "discovered": r[5], "new_records": r[6],
                "duplicates": r[7], "filtered": r[8],
                "errors": errs,
            })
        return out

    # ---- Search ----

    def search(self, query: str, source: str | None = None, limit: int = 20) -> list[dict]:
        """Full-text search via FTS5, returns lightweight summaries.

        The query is wrapped as an FTS5 phrase so hyphens / dots / other special
        chars in user input don't blow up the parser. Use a phrase query so
        `memory-pipeline` matches the literal token rather than being parsed as
        `column:value`.
        """
        # Sanitize: strip surrounding whitespace, escape internal double quotes,
        # wrap as phrase.
        safe = '"' + query.strip().replace('"', '""') + '"'
        with self._connect(self.index_path) as c:
            if source:
                rows = c.execute(
                    """SELECT r.id, r.source, r.agent, r.project, r.role,
                              r.captured_at, r.occurred_at, r.json_path,
                              snippet(records_fts, 5, '[', ']', '…', 12) AS snip
                       FROM records_fts
                       JOIN records r ON r.id = records_fts.id
                       WHERE records_fts MATCH ? AND r.source = ?
                       ORDER BY rank LIMIT ?""",
                    (safe, source, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    """SELECT r.id, r.source, r.agent, r.project, r.role,
                              r.captured_at, r.occurred_at, r.json_path,
                              snippet(records_fts, 5, '[', ']', '…', 12) AS snip
                       FROM records_fts
                       JOIN records r ON r.id = records_fts.id
                       WHERE records_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (safe, limit),
                ).fetchall()
        return [
            {
                "id": r[0], "source": r[1], "agent": r[2], "project": r[3],
                "role": r[4], "captured_at": r[5], "occurred_at": r[6],
                "json_path": r[7], "snippet": r[8],
            }
            for r in rows
        ]

    def stats(self) -> dict:
        with self._connect(self.index_path) as c:
            total = c.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            by_source = dict(c.execute(
                "SELECT source, COUNT(*) FROM records GROUP BY source ORDER BY 2 DESC"
            ).fetchall())
        return {"total": total, "by_source": by_source}

    # ---- Watermarks ----

    def load_watermarks(self) -> dict[str, Watermark]:
        if not self.watermarks_path.exists():
            return {}
        try:
            raw = json.loads(self.watermarks_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return {k: Watermark.from_dict(v) for k, v in raw.items()}

    def save_watermarks(self, wms: dict[str, Watermark]) -> None:
        out = {k: v.to_dict() for k, v in wms.items()}
        self.watermarks_path.write_text(
            json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def upsert_watermark(self, wm: Watermark) -> None:
        wms = self.load_watermarks()
        wms[f"{wm.source}::{wm.source_key}"] = wm
        self.save_watermarks(wms)


__all__ = ["RawStore"]
