"""Tests for the raw store."""
from memloom.records import MemoryRecord, RunSummary
from memloom.store import RawStore


def test_upsert_and_search(tmp_path):
    store = RawStore(tmp_path)
    rec = MemoryRecord(
        source="openclaw",
        source_key="memory/2026-07-18.md",
        role="daily_note",
        content="Working on memory pipeline with sqlite and embeddings",
    )
    assert store.upsert(rec) is True
    assert store.upsert(rec) is False  # idempotent
    results = store.search("embeddings")
    assert len(results) >= 1
    assert results[0]["source"] == "openclaw"


def test_record_run(tmp_path):
    store = RawStore(tmp_path)
    s = RunSummary(source="openclaw", host="local", discovered=5, new_records=3)
    s.finish()
    store.record_run(s)
    runs = store.recent_runs()
    assert len(runs) == 1
    assert runs[0]["new_records"] == 3


def test_stats(tmp_path):
    store = RawStore(tmp_path)
    for i in range(3):
        store.upsert(MemoryRecord(
            source="openclaw", source_key=f"k{i}", content=f"content {i}",
        ))
    store.upsert(MemoryRecord(source="claude_code", source_key="k0", content="hello"))
    stats = store.stats()
    assert stats["total"] == 4
    assert stats["by_source"]["openclaw"] == 3
    assert stats["by_source"]["claude_code"] == 1


def test_watermark_persistence(tmp_path):
    store = RawStore(tmp_path)
    from memloom.records import Watermark
    wm = Watermark(source="openclaw", source_key="MEMORY.md", last_seen_ms=12345, last_hash="abc")
    store.upsert_watermark(wm)
    loaded = store.load_watermarks()
    assert loaded["openclaw::MEMORY.md"].last_seen_ms == 12345


def test_get_record_roundtrip(tmp_path):
    store = RawStore(tmp_path)
    rec = MemoryRecord(
        source="test",
        source_key="k1",
        content="hello admin",
        role="note",
    )
    store.upsert(rec)
    got = store.get_record(rec.id)
    assert got is not None
    assert got["id"] == rec.id
    assert got["record"]["content"] == "hello admin"
    assert "hello admin" in got["markdown"]
    assert store.get_record("rec_nonexistent") is None
