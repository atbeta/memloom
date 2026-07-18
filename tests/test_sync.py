"""Tests for memloom.sync."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from memloom.records import MemoryRecord
from memloom.sync.adapter import SyncAdapter, WatermarkStore
from memloom.sync.antigravity import AntigravityAdapter
from memloom.sync.codex import CodexAdapter
from memloom.sync.config import SourceConfig, SyncConfig
from memloom.sync.kilocode import KiloCodeAdapter
from memloom.sync.opencode import OpenCodeAdapter
from memloom.sync.qoder import QoderAdapter


# ── Config tests ────────────────────────────────────────────────────────────

def test_sync_config_from_dict():
    cfg = SyncConfig(
        endpoint="http://localhost:8789/ingest",
        api_key="test-key",
        batch_size=200,
        sources=[SourceConfig(type="opencode", db="/tmp/test.db")],
    )
    assert cfg.batch_size == 200
    assert len(cfg.sources) == 1
    assert cfg.sources[0].db == "/tmp/test.db"


def test_sync_config_batch_size_bounds():
    with pytest.raises(ValueError):
        SyncConfig(batch_size=0)
    with pytest.raises(ValueError):
        SyncConfig(batch_size=10001)


# ── WatermarkStore tests ─────────────────────────────────────────────────────

def test_watermark_store_save_load(tmp_path: Path):
    store = WatermarkStore(tmp_path)
    store.save({"opencode": 1234567890000, "codex": 987654321000})
    loaded = store.load()
    assert loaded["opencode"] == 1234567890000
    assert loaded["codex"] == 987654321000


def test_watermark_store_empty(tmp_path: Path):
    store = WatermarkStore(tmp_path / "nonexistent")
    assert store.load() == {}


# ── SyncAdapter base tests ───────────────────────────────────────────────────

class _FakeAdapter(SyncAdapter):
    source_type = "fake"

    def extract(self, since_ms: int | None = None) -> list[MemoryRecord]:
        return [
            MemoryRecord(source="fake", source_key="k1", content="hello"),
            MemoryRecord(source="fake", source_key="k2", content="world"),
        ]

    def get_latest_cursor(self) -> int:
        return 1000000000000


def test_adapter_source_path_expansion():
    a = _FakeAdapter("~/test-db.db")
    assert a.source_path != "~/test-db.db"
    assert a.source_path.endswith("test-db.db")


def test_adapter_extract_returns_memory_records():
    a = _FakeAdapter("/tmp/test.db")
    records = a.extract()
    assert len(records) == 2
    assert all(isinstance(r, MemoryRecord) for r in records)
    assert records[0].source == "fake"
    assert records[0].id.startswith("rec_")


def test_adapter_get_latest_cursor():
    a = _FakeAdapter("/tmp/test.db")
    assert a.get_latest_cursor() == 1000000000000


# ── OpenCode adapter tests ───────────────────────────────────────────────────

def _make_opencode_db(path: Path):
    db = sqlite3.connect(str(path))
    db.execute("""
        CREATE TABLE IF NOT EXISTS session (
            id TEXT PRIMARY KEY, title TEXT, time_created INTEGER,
            time_updated INTEGER, model TEXT, agent TEXT, path TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS message (
            id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER,
            data TEXT
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS part (
            id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
            time_created INTEGER, data TEXT
        )
    """)

    now = int(time.time() * 1000)
    sid = "ses_test123"
    db.execute(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sid, "Test Session", now, now, "gpt-5", "build", "/tmp/testproject"),
    )
    mid1 = "msg_1"
    mid2 = "msg_2"
    db.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?)",
        (mid1, sid, now, json.dumps({"role": "user"})),
    )
    db.execute(
        "INSERT INTO message VALUES (?, ?, ?, ?)",
        (mid2, sid, now + 1, json.dumps({"role": "assistant"})),
    )
    db.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
        ("p1", mid1, sid, now, json.dumps({"type": "text", "text": "What is the status?"})),
    )
    db.execute(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
        ("p2", mid2, sid, now + 1, json.dumps({"type": "text", "text": "All systems operational."})),
    )
    db.commit()
    db.close()
    return path


def test_opencode_adapter(tmp_path: Path):
    db_path = tmp_path / "opencode.db"
    _make_opencode_db(db_path)
    a = OpenCodeAdapter(str(db_path))
    records = a.extract()
    assert len(records) == 1
    r = records[0]
    assert r.source == "opencode"
    assert r.source_key == "ses_test123"
    assert "What is the status?" in r.content
    assert "All systems operational" in r.content
    assert r.project == "testproject"
    assert r.agent == "opencode:build"


def test_opencode_adapter_incremental(tmp_path: Path):
    db_path = tmp_path / "opencode.db"
    _make_opencode_db(db_path)
    a = OpenCodeAdapter(str(db_path))
    future = int((time.time() + 86400) * 1000)
    records = a.extract(since_ms=future)
    assert len(records) == 0


def test_opencode_nonexistent_db():
    a = OpenCodeAdapter("/nonexistent/path.db")
    assert a.extract() == []
    assert a.get_latest_cursor() == 0


# ── KiloCode adapter tests ───────────────────────────────────────────────────

def _make_kilocode_tasks(tmp: Path):
    task_dir = tmp / "019ca7e8-e6aa-74bd-b00d-18ae5d75767e"
    task_dir.mkdir(parents=True)
    conv = [
        {"role": "user", "content": [{"type": "text", "text": "Help me refactor"}], "ts": 1752800000},
        {"role": "assistant", "content": [{"type": "text", "text": "I will help"}], "ts": 1752800100},
    ]
    (task_dir / "api_conversation_history.json").write_text(json.dumps(conv))
    (task_dir / "task_metadata.json").write_text(json.dumps({"taskTitle": "Refactor module"}))
    return tmp


def test_kilocode_adapter(tmp_path: Path):
    tasks_dir = _make_kilocode_tasks(tmp_path)
    a = KiloCodeAdapter(str(tasks_dir))
    records = a.extract()
    assert len(records) == 1
    r = records[0]
    assert r.source == "kilocode"
    assert "Help me refactor" in r.content
    assert "I will help" in r.content
    assert r.raw_meta["title"] == "Refactor module"
    assert r.raw_meta["message_count"] == 2


def test_kilocode_nonexistent_dir():
    a = KiloCodeAdapter("/nonexistent/tasks")
    assert a.extract() == []


# ── Antigravity adapter tests ────────────────────────────────────────────────

def _make_antigravity_brain(tmp: Path):
    region = tmp / "0720659b-b7da-4149-b875-2526ebd5e462"
    region.mkdir(parents=True)
    (region / "task.md").write_text("# Task\n\nDo the thing.")
    (region / "implementation_plan.md").write_text("# Plan\n\nStep 1: start.")
    return tmp


def test_antigravity_adapter(tmp_path: Path):
    brain_dir = _make_antigravity_brain(tmp_path)
    a = AntigravityAdapter(str(brain_dir))
    records = a.extract()
    assert len(records) == 2
    assert {r.content for r in records} == {"# Task\n\nDo the thing.", "# Plan\n\nStep 1: start."}


def test_antigravity_nonexistent_dir():
    a = AntigravityAdapter("/nonexistent/brain")
    assert a.extract() == []


# ── Codex adapter tests ──────────────────────────────────────────────────────

def _make_codex_db_and_rollout(tmp: Path):
    thread_id = "019cb3d0-600f-7833-abca-5134b23acffc"
    sessions_dir = tmp / "sessions" / "2026" / "03" / "03"
    sessions_dir.mkdir(parents=True)
    rollout_path = sessions_dir / f"rollout-2026-03-03T21-08-23-{thread_id}.jsonl"

    lines = [
        json.dumps({"timestamp": "2026-03-03T13:08:28Z", "type": "session_meta", "payload": {"id": thread_id}}),
        json.dumps({"timestamp": "2026-03-03T13:08:28Z", "type": "event_msg", "payload": {"type": "user_message", "message": "Can you understand this project?"}}),
        json.dumps({"timestamp": "2026-03-03T13:08:30Z", "type": "event_msg", "payload": {"type": "agent_message", "message": "Yes, I understand the architecture.", "phase": "final_answer"}}),
        json.dumps({"timestamp": "2026-03-03T13:08:31Z", "type": "event_msg", "payload": {"type": "agent_reasoning", "text": "Confirming project structure."}}),
    ]
    rollout_path.write_text("\n".join(lines))

    db = sqlite3.connect(str(tmp / "state_5.sqlite"))
    db.execute("""
        CREATE TABLE IF NOT EXISTS threads (
            id TEXT PRIMARY KEY, title TEXT, created_at INTEGER,
            cwd TEXT, model_provider TEXT, model TEXT, rollout_path TEXT
        )
    """)
    db.execute(
        "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?)",
        (thread_id, "Check project", 1782232187, "/tmp/relaycraft", "openai", "gpt-5.3-codex", str(rollout_path)),
    )
    db.commit()
    db.close()
    return tmp


def test_codex_adapter(tmp_path: Path):
    data_dir = _make_codex_db_and_rollout(tmp_path)
    a = CodexAdapter(str(data_dir / "state_5.sqlite"))
    records = a.extract()
    assert len(records) == 1
    r = records[0]
    assert r.source == "codex"
    assert "Can you understand this project?" in r.content
    assert "Yes, I understand the architecture" in r.content
    assert "Confirming project structure" in r.content
    assert r.project == "relaycraft"



def test_codex_nonexistent_db():
    a = CodexAdapter("/nonexistent/state.db")
    assert a.extract() == []


# ── Qoder adapter tests ──────────────────────────────────────────────────────

def _make_qoder_db(path: Path):
    db = sqlite3.connect(str(path))
    db.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT, path TEXT, created_at INTEGER)")
    db.execute("CREATE TABLE IF NOT EXISTS chats (id TEXT PRIMARY KEY, name TEXT, project_id TEXT, created_at INTEGER)")
    db.execute("CREATE TABLE IF NOT EXISTS sub_chats (id TEXT PRIMARY KEY, name TEXT, chat_id TEXT, mode TEXT)")
    db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, message_id TEXT, chat_id TEXT, sub_chat_id TEXT,
            sequence INTEGER, role TEXT, parts TEXT DEFAULT '[]',
            searchable_text TEXT, metadata TEXT DEFAULT '{}', created_at INTEGER
        )
    """)

    now = int(time.time() * 1000)
    pid, cid, scid = "proj1", "chat1", "sub1"
    db.execute("INSERT INTO projects VALUES (?, ?, ?, ?)", (pid, "test-project", "/tmp/test", now))
    db.execute("INSERT INTO chats VALUES (?, ?, ?, ?)", (cid, "Test Chat", pid, now))
    db.execute("INSERT INTO sub_chats VALUES (?, ?, ?, ?)", (scid, "Test Chat", cid, "agent"))
    db.execute(
        "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("msg1", "m1", cid, scid, 0, "user", json.dumps([{"type": "text", "text": "Hello"}]),
         "Hello", "{}", now),
    )
    db.execute(
        "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("msg2", "m2", cid, scid, 1, "assistant", json.dumps([{"type": "text", "text": "Hi there"}]),
         "Hi there", "{}", now + 1),
    )
    db.commit()
    db.close()
    return path


def test_qoder_adapter(tmp_path: Path):
    db_path = _make_qoder_db(tmp_path / "agents.db")
    a = QoderAdapter(str(db_path))
    records = a.extract()
    assert len(records) == 1
    r = records[0]
    assert r.source == "qoder"
    assert "Hello" in r.content
    assert "Hi there" in r.content
    assert r.project == "test-project"


def test_qoder_nonexistent_db():
    a = QoderAdapter("/nonexistent/agents.db")
    assert a.extract() == []
