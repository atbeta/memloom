"""Tests for the v0.4 hybrid search (FTS5 + sqlite-vec + RRF) and embed client."""
from __future__ import annotations

import struct

import pytest

from memloom.records import MemoryRecord
from memloom.store import RawStore, VECTOR_DIM


# ---------- helpers ----------

def _vec(positions: list[int], dim: int = VECTOR_DIM) -> list[float]:
    """Make a dim-dim vector with 1.0 at the given positions."""
    v = [0.0] * dim
    for p in positions:
        v[p] = 1.0
    return v


def _make_store_with_records() -> tuple[RawStore, list[MemoryRecord]]:
    import tempfile
    tmp = tempfile.mkdtemp()
    store = RawStore(tmp)
    recs = [
        ("rec_a", "RelayCraft 是一个网络调试工具", "openclaw_session"),
        ("rec_b", "PicFast 是一个图床服务", "openclaw_session"),
        ("rec_c", "今天天气真好适合出去走走", "openclaw_session"),
    ]
    out = []
    for rid, content, source in recs:
        r = MemoryRecord(
            source=source, source_key=rid, role="conversation_turn", content=content,
        )
        # use a known id for predictable ordering
        r.id = rid
        store.upsert(r)
        out.append(r)
    return store, out


# ---------- hybrid search tests ----------

def test_hybrid_search_requires_vec():
    """If query_vec is None, hybrid falls back to FTS5."""
    store, _ = _make_store_with_records()
    out = store.hybrid_search("PicFast", query_vec=None, limit=10)
    assert any("PicFast" in (r.get("snippet") or "") for r in out)


def test_hybrid_search_finds_semantically_similar():
    """FTS5 only finds literal matches. With a vector, semantic matches rank too."""
    store, _ = _make_store_with_records()
    # Add vectors: rec_a (RelayCraft) at positions [0, 100]
    store.upsert_vector("rec_a", _vec([0, 100]))
    store.upsert_vector("rec_b", _vec([1, 101]))
    store.upsert_vector("rec_c", _vec([2, 102]))

    # Query vector matches rec_a (RelayCraft)
    qvec = _vec([0, 100])
    out = store.hybrid_search("随便", qvec, limit=3)
    # rec_a should be top (vector match + 1 FTS5 hit)
    assert out[0]["id"] == "rec_a"


def test_hybrid_search_rrf_boosts_dual_matches():
    """A doc that both FTS5 and vector rank highly should have n_methods=2 and high score."""
    store, _ = _make_store_with_records()
    store.upsert_vector("rec_a", _vec([0, 100]))
    store.upsert_vector("rec_b", _vec([1, 101]))
    store.upsert_vector("rec_c", _vec([2, 102]))

    # Query "PicFast" (FTS5 hit) + vector for rec_b (vector hit) → rec_b in both
    qvec = _vec([1, 101])
    out = store.hybrid_search("PicFast", qvec, limit=3)
    by_id = {r["id"]: r for r in out}
    assert "rec_b" in by_id
    assert by_id["rec_b"]["n_methods"] == 2  # found by both FTS5 + vector


def test_hybrid_search_respects_source_filter():
    store, _ = _make_store_with_records()
    store.upsert_vector("rec_a", _vec([0]))
    store.upsert_vector("rec_b", _vec([1]))

    out = store.hybrid_search("RelayCraft", _vec([0, 1]), source="openclaw_session", limit=10)
    assert all(r["source"] == "openclaw_session" for r in out)


def test_upsert_vector_replaces_existing():
    store, _ = _make_store_with_records()
    assert store.upsert_vector("rec_a", _vec([0])) is True
    assert store.upsert_vector("rec_a", _vec([1])) is False  # replaced
    assert store.vector_count() == 1


def test_upsert_vector_raises_for_missing_record():
    import tempfile
    store = RawStore(tempfile.mkdtemp())
    with pytest.raises(KeyError):
        store.upsert_vector("nonexistent", _vec([0]))


def test_vector_dimension_enforced():
    import tempfile
    store = RawStore(tempfile.mkdtemp())
    rec = MemoryRecord(
        source="x", source_key="k", role="r", content="c",
    )
    store.upsert(rec)
    with pytest.raises(ValueError, match="dim"):
        store.upsert_vector(rec.id, [0.0] * 100)  # wrong dim


# ---------- embed client tests ----------

def test_embedder_config_defaults():
    from memloom.embed import EmbedConfig
    cfg = EmbedConfig()
    assert cfg.dimension == 1024
    assert cfg.model == "bge-m3-mlx-fp16"
    assert cfg.enabled is True


def test_embedder_truncate_long_input():
    from memloom.embed import EmbedConfig, Embedder
    cfg = EmbedConfig(max_chars=100, base_url="http://localhost:1", enabled=False)
    e = Embedder(cfg)
    big = "x" * 5000
    truncated = e._truncate(big)
    assert len(truncated) == 100


def test_embedder_returns_zero_vectors_on_total_failure():
    """If all retries fail, we get zero vectors (caller can still store them)."""
    from memloom.embed import EmbedConfig, Embedder
    cfg = EmbedConfig(
        base_url="http://localhost:1",  # unreachable
        max_retries=1,
        enabled=True,
    )
    e = Embedder(cfg)
    vecs = e.embed_batch(["hello", "world"])
    assert len(vecs) == 2
    assert all(len(v) == 1024 for v in vecs)
    assert all(v == [0.0] * 1024 for v in vecs)


def test_embedder_handles_empty_strings():
    """Empty inputs in a batch get zero vectors, others embed normally."""
    from memloom.embed import EmbedConfig, Embedder
    # Mock the session to return a single vector for non-empty inputs
    from unittest.mock import MagicMock
    cfg = EmbedConfig(base_url="http://localhost:1", enabled=True, max_retries=1)
    e = Embedder(cfg)
    # Patch _embed_with_retry to return one vector per non-empty input
    original = e._embed_with_retry
    def fake(texts):
        return [[0.5] * 1024 for _ in texts]
    e._embed_with_retry = fake
    out = e.embed_batch(["", "hello", "", "world"])
    assert len(out) == 4
    # Empty inputs → zero vectors
    assert out[0] == [0.0] * 1024
    assert out[2] == [0.0] * 1024
    # Non-empty → 0.5 vectors
    assert out[1] == [0.5] * 1024
    assert out[3] == [0.5] * 1024


# ---------- store stats ----------

def test_stats_includes_vectors():
    import tempfile
    store = RawStore(tempfile.mkdtemp())
    rec = MemoryRecord(source="x", source_key="k", role="r", content="c")
    store.upsert(rec)
    stats = store.stats()
    assert "vectors" in stats
    assert stats["vectors"] == 0

    store.upsert_vector(rec.id, _vec([0, 1]))
    stats = store.stats()
    assert stats["vectors"] == 1


# ---------- vector count and migration ----------

def test_existing_index_gets_vec0_table_on_init():
    """Opening an old index.sqlite (no vec0) should add the vec0 table."""
    import tempfile, sqlite3, struct
    tmp = tempfile.mkdtemp()

    # Create a v0.3-style index without vec0
    db_path = __import__("pathlib").Path(tmp) / "index.sqlite"
    raw_dir = __import__("pathlib").Path(tmp) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(db_path))
    c.executescript("""
    CREATE TABLE records (id TEXT PRIMARY KEY, source TEXT, source_key TEXT,
        agent TEXT, project TEXT, visibility TEXT, role TEXT,
        captured_at INTEGER, occurred_at INTEGER, content_hash TEXT,
        raw_ref TEXT, json_path TEXT, md_path TEXT, created_at INTEGER);
    CREATE VIRTUAL TABLE records_fts USING fts5(id UNINDEXED, source, agent,
        project, role, content, tokenize='unicode61 remove_diacritics 2');
    """)
    c.execute("""INSERT INTO records VALUES ('r1','x','k',NULL,NULL,NULL,'r',1,NULL,NULL,NULL,'','',1)""")
    c.commit()
    c.close()

    # Now open with RawStore (should auto-add vec0)
    store = RawStore(tmp)
    # Verify vec0 table exists
    c = sqlite3.connect(str(db_path))
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert "records_vec" in tables