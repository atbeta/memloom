"""Tests for the privacy filter."""
from memory_pipeline.pipeline.privacy import PrivacyFilter
from memory_pipeline.records import MemoryRecord


def test_strips_openai_key():
    f = PrivacyFilter(patterns=[r"sk-[A-Za-z0-9_-]{20,}"])
    r = MemoryRecord(source="x", source_key="k", content="my key is sk-abcdefghijklmnopqrstuvwxyz12")
    r2, changed = f.filter_record(r)
    assert changed
    assert "sk-abcdefghijklmnopqrstuvwxyz12" not in r2.content
    assert "[REDACTED]" in r2.content


def test_strips_github_pat():
    f = PrivacyFilter(patterns=[r"ghp_[A-Za-z0-9]{36,}"])
    r = MemoryRecord(source="x", source_key="k", content="token=ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    r2, changed = f.filter_record(r)
    assert changed
    assert "ghp_aaa" not in r2.content


def test_unchanged_when_no_secret():
    f = PrivacyFilter(patterns=[r"sk-[A-Za-z0-9_-]{20,}"])
    r = MemoryRecord(source="x", source_key="k", content="just a regular note, no secrets here")
    r2, changed = f.filter_record(r)
    assert not changed
    assert r2.content == r.content


def test_strips_in_raw_meta_text():
    f = PrivacyFilter(patterns=[r"sk-[A-Za-z0-9_-]{20,}"])
    r = MemoryRecord(
        source="x", source_key="k",
        content="clean",
        raw_meta={"text": "leaked sk-abcdefghijklmnopqrstuvwxyz12 in meta"},
    )
    r2, changed = f.filter_record(r)
    assert changed
    assert "sk-abcdefghijklmnopqrstuvwxyz12" not in r2.raw_meta["text"]


def test_multiple_patterns():
    f = PrivacyFilter(patterns=[
        r"sk-[A-Za-z0-9_-]{20,}",
        r"AKIA[0-9A-Z]{16}",
    ])
    r = MemoryRecord(source="x", source_key="k", content="sk-abcdefghijklmnopqrstuvwxyz12 and AKIAIOSFODNN7EXAMPLE")
    r2, _ = f.filter_record(r)
    assert "sk-abcdef" not in r2.content
    assert "AKIAIOSFODNN7EXAMPLE" not in r2.content
    assert r2.content.count("[REDACTED]") == 2
