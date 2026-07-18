"""Tests for MemoryRecord / Watermark data classes."""
from memloom.records import MemoryRecord, Watermark, content_hash, record_id


def test_record_id_deterministic():
    a = record_id("openclaw", "memory/2026-07-18.md")
    b = record_id("openclaw", "memory/2026-07-18.md")
    c = record_id("openclaw", "memory/2026-07-19.md")
    assert a == b
    assert a != c
    assert a.startswith("rec_")


def test_content_hash():
    h1 = content_hash("hello")
    h2 = content_hash("hello")
    h3 = content_hash("world")
    assert h1 == h2
    assert h1 != h3
    assert h1.startswith("sha256:")


def test_memoryrecord_post_init():
    r = MemoryRecord(source="openclaw", source_key="MEMORY.md", content="hi")
    assert r.id.startswith("rec_")
    assert r.content_hash.startswith("sha256:")
    assert r.captured_at > 0


def test_memoryrecord_roundtrip_json():
    r = MemoryRecord(
        source="openclaw",
        source_key="MEMORY.md",
        agent="openclaw",
        project=None,
        role="long_term_memory",
        content="hello\nworld",
        tags=["foo", "bar"],
    )
    j = r.to_json()
    r2 = MemoryRecord.from_json(j)
    assert r2.id == r.id
    assert r2.source == r.source
    assert r2.content == r.content
    assert r2.tags == r.tags


def test_memoryrecord_from_dict_ignores_unknown():
    d = {"source": "x", "source_key": "k", "unknown_key": "ignored"}
    r = MemoryRecord.from_dict(d)
    assert r.source == "x"


def test_memoryrecord_markdown():
    r = MemoryRecord(
        source="openclaw",
        source_key="MEMORY.md",
        agent="openclaw",
        role="long_term_memory",
        content="hello world",
    )
    md = r.to_markdown()
    assert "# rec_" in md
    assert "openclaw" in md
    assert "hello world" in md


def test_watermark_roundtrip():
    w = Watermark(source="openclaw", source_key="MEMORY.md", last_seen_ms=12345, last_hash="abc")
    w2 = Watermark.from_dict(w.to_dict())
    assert w2.source == "openclaw"
    assert w2.last_seen_ms == 12345
