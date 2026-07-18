"""Tests for conversation chunker and pluggable pipeline."""
from memloom.pipeline.chunk import ConversationChunker
from memloom.pipeline.step import PluggablePipeline
from memloom.pipeline.builtins import PrivacyStep  # triggers registration
from memloom.records import MemoryRecord


def test_chunker_passthrough_small():
    c = ConversationChunker(target_size=8192)
    rec = MemoryRecord(source="test", source_key="k1", content="short", role="note")
    results = list(c.process(rec))
    assert len(results) == 1
    assert results[0].content == "short"


def test_chunker_splits_large_at_turn_boundaries():
    c = ConversationChunker(target_size=500)
    content = "\n".join([
        "## user", "", "A" * 400,
        "",
        "## assistant", "", "B" * 400,
        "",
        "## user", "", "C" * 400,
    ])
    rec = MemoryRecord(source="test", source_key="k1", content=content, role="conversation_turn")
    results = list(c.process(rec))
    assert len(results) > 1
    # Each chunk should contain at least one turn
    for r in results:
        assert "## user" in r.content or "## assistant" in r.content


def test_chunker_preserves_metadata():
    c = ConversationChunker(target_size=100)
    content = "\n".join(["## user", "", "X" * 200, "", "## assistant", "", "Y" * 200])
    rec = MemoryRecord(
        source="test", source_key="k1", content=content, role="note",
        agent="agent1", project="p1", occurred_at=1234567890000,
    )
    results = list(c.process(rec))
    assert len(results) == 2
    for r in results:
        assert r.source == "test"
        assert r.agent == "agent1"
        assert r.project == "p1"


def test_pluggable_pipeline_registry():
    from memloom.pipeline.step import REGISTRY
    assert "privacy" in REGISTRY
    assert "denoise" in REGISTRY
    assert "chunker" in REGISTRY
    assert "tag" in REGISTRY
    assert "dedup" in REGISTRY


def test_pluggable_pipeline_chains_steps():
    """Test that pipeline chains: tag → dedup (simplest chain)."""
    from memloom.pipeline.step import REGISTRY

    pipeline = PluggablePipeline()
    pipeline.add(REGISTRY["tag"]())
    pipeline.add(REGISTRY["dedup"]())

    rec = MemoryRecord(source="test", source_key="k1", content="hello", role="note")
    results = list(pipeline.run(rec))
    assert len(results) == 1  # first time = new record
    assert "source:test" in results[0].tags

    # Second run with same source_key → dedup should skip
    rec2 = MemoryRecord(source="test", source_key="k1", content="hello", role="note")
    results2 = list(pipeline.run(rec2))
    assert len(results2) == 0  # dedup skipped
