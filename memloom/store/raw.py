"""Raw store: writes records to disk in three forms + SQLite FTS5 + sqlite-vec.

Layout under ``data_root``::

    data_root/
      raw/
        <source>/
          <source_key_basename>.json    # full structured record
          <source_key_basename>.md      # human-readable mirror
          attachments/                  # optional binary blobs (images, etc.)
      index.sqlite                      # metadata + FTS5 + vec0
      runs.sqlite                       # run history
      watermarks.json                   # per-source incremental cursors

Three writes per record (canonical):
  1. ``raw/<source>/<key>.json`` — full MemoryRecord
  2. ``raw/<source>/<key>.md``   — markdown view (grep/browse friendly)
  3. ``index.sqlite``            — row + FTS5 entry + vec0 entry for retrieval

Idempotency: writes are keyed by record.id; re-writing the same record is a
no-op. Collectors can re-run freely.
"""
from __future__ import annotations

import json
import sqlite3
import struct
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec

from ..records import MemoryRecord, RunSummary, Watermark


# ---------- Schema ----------

# Default vector dimension. Matches bge-m3 (1024). Change if you swap models.
VECTOR_DIM = 1024

_INDEX_SCHEMA = f"""
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

-- v0.4: vector index for hybrid search (sqlite-vec). rowid == records.rowid.
-- Created with IF NOT EXISTS so older index.sqlite files get it on next open.
CREATE VIRTUAL TABLE IF NOT EXISTS records_vec USING vec0(
  embedding float[{VECTOR_DIM}]
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
    """Thread-safe raw store backed by SQLite + filesystem + sqlite-vec."""

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
            # Enable sqlite-vec extension
            c.enable_load_extension(True)
            sqlite_vec.load(c)
            c.enable_load_extension(False)
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
            # Make sure vec0 is available on every connection (cheap: extension is idempotent)
            try:
                c.enable_load_extension(True)
                sqlite_vec.load(c)
                c.enable_load_extension(False)
            except Exception:
                pass
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

    def get_record(self, record_id: str) -> dict | None:
        """Load a record by id from the index + on-disk JSON/Markdown.

        Returns None if the id is unknown. ``record`` is the parsed JSON
        payload; ``markdown`` is the human-readable mirror (may be empty).
        """
        with self._connect(self.index_path) as c:
            row = c.execute(
                """SELECT id, source, source_key, agent, project, role,
                          captured_at, occurred_at, json_path, md_path
                   FROM records WHERE id=?""",
                (record_id,),
            ).fetchone()
        if not row:
            return None
        json_path = Path(row[8])
        md_path = Path(row[9])
        record_data: dict = {}
        markdown = ""
        if json_path.is_file():
            record_data = json.loads(json_path.read_text(encoding="utf-8"))
        if md_path.is_file():
            markdown = md_path.read_text(encoding="utf-8")
        return {
            "id": row[0],
            "source": row[1],
            "source_key": row[2],
            "agent": row[3] or "",
            "project": row[4],
            "role": row[5] or "",
            "captured_at": row[6],
            "occurred_at": row[7],
            "json_path": str(json_path),
            "md_path": str(md_path),
            "record": record_data,
            "markdown": markdown,
        }

    def _record_rowid(self, c: sqlite3.Connection, record_id: str) -> int | None:
        """Get the integer rowid of a record (for joining with records_vec)."""
        row = c.execute("SELECT rowid FROM records WHERE id=?", (record_id,)).fetchone()
        return row[0] if row else None

    def upsert(self, record: MemoryRecord) -> bool:
        """Write record to disk + index. Returns True if newly inserted, False if existing.

        Note: this does NOT touch the vector index. Call ``upsert_vector()`` after
        embedding the record's content. Keeping the two writes separate lets the
        embedder be a swappable backend (or turned off entirely).
        """
        json_path, md_path = self._key_to_paths(record.source, record.source_key)
        raw_ref = str(json_path.relative_to(self.root))

        json_path.write_text(record.to_json(), encoding="utf-8")
        md_path.write_text(record.to_markdown(), encoding="utf-8")

        with self._connect(self.index_path) as c:
            existing = c.execute("SELECT 1 FROM records WHERE id=?", (record.id,)).fetchone()
            if existing:
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

    # ---- Vector I/O (v0.4) ----

    def upsert_vector(self, record_id: str, vector: list[float]) -> bool:
        """Store (or replace) the embedding for a record.

        Returns True if a new vector was inserted, False if replaced.
        Raises KeyError if the record doesn't exist (FTS index must lead).
        """
        if len(vector) != VECTOR_DIM:
            raise ValueError(
                f"vector dim {len(vector)} != expected {VECTOR_DIM}"
            )
        packed = struct.pack(f"<{VECTOR_DIM}f", *vector)
        with self._connect(self.index_path) as c:
            rowid = self._record_rowid(c, record_id)
            if rowid is None:
                raise KeyError(f"record not found: {record_id}")
            existing = c.execute(
                "SELECT 1 FROM records_vec WHERE rowid=?", (rowid,)
            ).fetchone()
            if existing:
                c.execute(
                    "UPDATE records_vec SET embedding=? WHERE rowid=?",
                    (packed, rowid),
                )
                return False
            c.execute(
                "INSERT INTO records_vec(rowid, embedding) VALUES (?, ?)",
                (rowid, packed),
            )
            return True

    def vector_count(self) -> int:
        with self._connect(self.index_path) as c:
            return c.execute("SELECT COUNT(*) FROM records_vec").fetchone()[0]

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
        """FTS5-only full-text search. Returns lightweight summaries.

        For hybrid (FTS5 + vector) search, use :meth:`hybrid_search`.
        """
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

    def hybrid_search(
        self,
        query: str,
        query_vec: list[float] | None,
        source: str | None = None,
        limit: int = 20,
        rrf_k: int = 60,
        candidate_k: int = 50,
    ) -> list[dict]:
        """Hybrid search: FTS5 (keyword) + sqlite-vec (semantic), fused via RRF.

        Each retriever pulls its top ``candidate_k`` results, then we fuse the
        rankings with Reciprocal Rank Fusion. A document that both retrievers
        rank highly will rise to the top.

        If ``query_vec`` is None, falls back to FTS5-only (same as :meth:`search`).
        """
        if query_vec is None:
            return self.search(query, source=source, limit=limit)

        fts_query = '"' + query.strip().replace('"', '""') + '"'
        packed = struct.pack(f"<{VECTOR_DIM}f", *query_vec)

        # The fusion happens in a single SQL statement.
        # k=60 is the standard RRF smoothing constant.
        # We pass query_vec as the second positional parameter (after fts_query)
        # because sqlite-vec MATCH needs a positional bind.
        sql = """
        WITH
          fts_results AS (
            SELECT records_fts.id AS id,
                   ROW_NUMBER() OVER (ORDER BY records_fts.rank) AS rrf_rank
              FROM records_fts
              JOIN records r ON r.id = records_fts.id
             WHERE records_fts MATCH ?
               AND (? IS NULL OR r.source = ?)
             ORDER BY records_fts.rank
             LIMIT ?
          ),
          vec_results AS (
            SELECT r.id AS id,
                   ROW_NUMBER() OVER (ORDER BY v.distance) AS rrf_rank
              FROM records_vec v
              JOIN records r ON r.rowid = v.rowid
             WHERE v.embedding MATCH ?
               AND k = ?
               AND (? IS NULL OR r.source = ?)
          ),
          combined AS (
            SELECT id, 1.0 / (? + rrf_rank) AS score FROM fts_results
            UNION ALL
            SELECT id, 1.0 / (? + rrf_rank) AS score FROM vec_results
          ),
          scored AS (
            SELECT id, SUM(score) AS rrf_score, COUNT(*) AS n_methods
              FROM combined
             GROUP BY id
          )
        SELECT
          r.id, r.source, r.agent, r.project, r.role,
          r.captured_at, r.occurred_at, r.json_path,
          snippet(records_fts, 5, '[', ']', '…', 12) AS snip,
          s.rrf_score, s.n_methods
          FROM scored s
          JOIN records r ON r.id = s.id
          LEFT JOIN records_fts ON records_fts.id = s.id
         ORDER BY s.rrf_score DESC, s.n_methods DESC
         LIMIT ?
        """
        with self._connect(self.index_path) as c:
            try:
                rows = c.execute(
                    sql,
                    (fts_query, source, source, candidate_k,  # fts_results params
                     packed, candidate_k, source, source,    # vec_results params
                     rrf_k, rrf_k,                            # combined params
                     limit),                                  # final limit
                ).fetchall()
            except sqlite3.OperationalError as e:
                # If vector index is empty or not yet populated, fall back
                if "records_vec" in str(e) or "no such" in str(e).lower():
                    return self.search(query, source=source, limit=limit)
                raise

        return [
            {
                "id": r[0], "source": r[1], "agent": r[2], "project": r[3],
                "role": r[4], "captured_at": r[5], "occurred_at": r[6],
                "json_path": r[7], "snippet": r[8],
                "rrf_score": r[9], "n_methods": r[10],
            }
            for r in rows
        ]

    def stats(self) -> dict:
        with self._connect(self.index_path) as c:
            total = c.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            by_source = dict(c.execute(
                "SELECT source, COUNT(*) FROM records GROUP BY source ORDER BY 2 DESC"
            ).fetchall())
            try:
                vec_total = c.execute("SELECT COUNT(*) FROM records_vec").fetchone()[0]
            except sqlite3.OperationalError:
                vec_total = 0
        return {"total": total, "by_source": by_source, "vectors": vec_total}

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


__all__ = ["RawStore", "VECTOR_DIM"]