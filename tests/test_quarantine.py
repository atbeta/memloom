"""Tests for the quarantine mechanism."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from memloom.records import MemoryRecord
from memloom.store import RawStore
from memloom.quarantine import (
    DEFAULT_TRIVIAL_RE,
    find_quarantine_candidates,
    list_quarantined,
    move_to_quarantine,
    restore_from_quarantine,
)


# ---- helpers ----

def _make_store_with(records: list[MemoryRecord]) -> tuple[RawStore, Path]:
    """Create a fresh store and add records directly via raw/ files."""
    tmp = Path(tempfile.mkdtemp())
    store = RawStore(str(tmp))
    for rec in records:
        json_path, md_path = store._key_to_paths(rec.source, rec.source_key)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(rec.to_json(), encoding="utf-8")
        md_path.write_text(rec.to_markdown(), encoding="utf-8")
        store.upsert(rec)
    return store, tmp


def _rec(rid: str, content: str, role: str = "conversation_turn", source: str = "x") -> MemoryRecord:
    r = MemoryRecord(
        source=source,
        source_key=rid,
        role=role,
        content=content,
    )
    r.id = rid
    return r


# ---- find_quarantine_candidates ----

def test_finds_too_short_content():
    store, tmp = _make_store_with([
        _rec("r1", "ok"),              # too short
        _rec("r2", "**USER**: hi\n\n**ASSISTANT**: hello, how can I help you today with your code review and merge request workflow here"),  # keep
    ])
    try:
        candidates = list(find_quarantine_candidates(store))
        ids = [r.id for r, _ in candidates]
        assert "r1" in ids
        assert "r2" not in ids
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_finds_trivial_patterns():
    # Trivial patterns only match non-conversation_turn content (since conv_turn
    # requires **USER**/**ASSISTANT** markers).
    store, tmp = _make_store_with([
        _rec("r1", "hello"),
        _rec("r2", "Test?"),
        _rec("r3", "ping"),
        _rec("r4", "1+1"),
        _rec("r5", "**USER**: lets discuss the deployment plan for the new service we are rolling out this week"),  # keep
    ])
    try:
        candidates = list(find_quarantine_candidates(store))
        ids = {r.id for r, _ in candidates}
        assert "r1" in ids
        assert "r2" in ids
        assert "r3" in ids
        assert "r4" in ids
        assert "r5" not in ids
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_finds_synthetic_roles():
    store, tmp = _make_store_with([
        _rec("r1", "stuff", role="_skip_marker"),
        _rec("r2", "stuff", role="_file_summary"),
        _rec("r3", "**USER**: real conversation about relaycraft\n\n**ASSISTANT**: yes I can help with that", role="conversation_turn"),
    ])
    try:
        candidates = list(find_quarantine_candidates(store))
        ids = {r.id for r, _ in candidates}
        assert "r1" in ids
        assert "r2" in ids
        assert "r3" not in ids
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_finds_incomplete_conversation_turn():
    """A conversation_turn with no USER section is likely truncated/incomplete."""
    store, tmp = _make_store_with([
        _rec("r1", "**ASSISTANT** (model): no user message here"),
        _rec("r2", "**USER**: hello\n\n**ASSISTANT**: hi"),
    ])
    try:
        candidates = list(find_quarantine_candidates(store))
        ids = {r.id for r, _ in candidates}
        assert "r1" in ids
        assert "r2" not in ids
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ---- move_to_quarantine ----

def test_move_moves_files_to_quarantine_dir():
    store, tmp = _make_store_with([_rec("r1", "real content")])
    try:
        result = move_to_quarantine(store, ["r1"], reason="test")
        assert result.moved == ["r1"]
        # Files moved
        quar_dir = tmp / "quarantine" / "x"
        assert (quar_dir / "r1.json").exists()
        assert (quar_dir / "r1.md").exists()
        # Original gone
        assert not (tmp / "raw" / "x" / "r1.json").exists()
        # Sidecar metadata
        sidecar = quar_dir / "r1.quarantine.json"
        assert sidecar.exists()
        meta = json.loads(sidecar.read_text())
        assert meta["reason"] == "test"
        assert meta["id"] == "r1"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_move_removes_from_index():
    store, tmp = _make_store_with([_rec("r1", "real content here please")])
    try:
        assert store.has("r1")
        move_to_quarantine(store, ["r1"], reason="test")
        assert not store.has("r1")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_move_not_found():
    store, tmp = _make_store_with([_rec("r1", "x")])
    try:
        result = move_to_quarantine(store, ["nonexistent"])
        assert "nonexistent" in result.not_found
        assert result.moved == []
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_move_updates_watermark():
    """After quarantine, the collector should NOT re-pull the record."""
    store, tmp = _make_store_with([_rec("r1", "x")])
    try:
        from memloom.records import Watermark
        wm_before = Watermark(
            source="x", source_key="r1", last_seen_ms=0, last_hash="", last_run_id="init",
        )
        store.upsert_watermark(wm_before)
        move_to_quarantine(store, ["r1"], reason="test")
        wm_after = store.load_watermarks().get("x::r1")
        assert wm_after is not None
        # Watermark should have a sentinel that signals "don't re-pull"
        assert wm_after.last_run_id == "quarantine"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ---- list_quarantined ----

def test_list_quarantined_returns_moved():
    store, tmp = _make_store_with([
        _rec("r1", "x"),
        _rec("r2", "y"),
    ])
    try:
        move_to_quarantine(store, ["r1", "r2"], reason="test")
        items = list_quarantined(store)
        ids = {i["id"] for i in items}
        assert ids == {"r1", "r2"}
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_list_quarantined_empty_when_nothing():
    store, tmp = _make_store_with([_rec("r1", "x")])
    try:
        assert list_quarantined(store) == []
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ---- restore ----

def test_restore_moves_files_back():
    store, tmp = _make_store_with([_rec("r1", "x")])
    try:
        move_to_quarantine(store, ["r1"], reason="test")
        result = restore_from_quarantine(store, ["r1"])
        assert "r1" in result["moved"]
        # Back in raw/
        assert (tmp / "raw" / "x" / "r1.json").exists()
        # Not in quarantine
        assert not (tmp / "quarantine" / "x" / "r1.json").exists()
        # Index has it again
        assert store.has("r1")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_round_trip_quarantine_restore():
    """End-to-end: collect → quarantine → restore → re-collect."""
    store, tmp = _make_store_with([_rec("r1", "useful content about something")])
    try:
        # 1) record present
        assert store.has("r1")
        # 2) quarantine
        move_to_quarantine(store, ["r1"], reason="test")
        assert not store.has("r1")
        # 3) restore
        restore_from_quarantine(store, ["r1"])
        assert store.has("r1")
        # 4) search works
        results = store.search("useful")
        assert any(r["id"] == "r1" for r in results)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
