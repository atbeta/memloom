"""Tests for the memloom-ingest HTTP server."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memloom.config import Config, EmbedConfig, HostConfig, PipelineConfig, PrivacyConfig
from memloom.ingest_server import create_app, generate_key
from memloom.records import MemoryRecord


# ---------- fixtures ----------


@pytest.fixture
def cfg_and_key():
    """A Config + matching API key, with embed disabled (no network)."""
    key = "test_key_" + "x" * 32
    os.environ["MEMLOOM_INGEST_KEY"] = key
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            pipeline=PipelineConfig(data_root=tmp),
            privacy=PrivacyConfig(enabled=True, strip_patterns=[r"sk-[a-z]{20}"]),
            hosts=[HostConfig(name="local", transport="local")],
            embed=EmbedConfig(enabled=False),
        )
        yield cfg, key
    os.environ.pop("MEMLOOM_INGEST_KEY", None)


@pytest.fixture
def client(cfg_and_key):
    cfg, key = cfg_and_key
    app = create_app(cfg)
    return TestClient(app), key


# ---------- tests ----------


def test_health_no_auth(client):
    c, _ = client
    r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "records" in body
    assert "vectors" in body


def test_stats_no_auth(client):
    c, _ = client
    r = c.get("/stats")
    assert r.status_code == 200
    assert "total" in r.json()


def test_ingest_requires_bearer(client):
    c, _ = client
    r = c.post("/ingest", json={"records": []})
    assert r.status_code == 401


def test_ingest_rejects_wrong_bearer(client):
    c, _ = client
    r = c.post(
        "/ingest",
        headers={"Authorization": "Bearer wrong-key"},
        json={"records": []},
    )
    assert r.status_code == 401


def test_ingest_rejects_non_bearer_scheme(client):
    c, _ = client
    r = c.post(
        "/ingest",
        headers={"Authorization": "Basic abc123"},
        json={"records": []},
    )
    assert r.status_code == 401


def test_ingest_server_misconfig_500(client, monkeypatch):
    """If MEMLOOM_INGEST_KEY is not set in server env, return 500."""
    c, _ = client
    monkeypatch.delenv("MEMLOOM_INGEST_KEY", raising=False)
    r = c.post(
        "/ingest",
        headers={"Authorization": "Bearer anything"},
        json={"records": [{"source": "x", "source_key": "k", "content": "hi"}]},
    )
    assert r.status_code == 500


def test_ingest_minimal_record(client):
    c, key = client
    r = c.post(
        "/ingest",
        headers={"Authorization": f"Bearer {key}"},
        json={"records": [{
            "source": "opencode",
            "source_key": "session-abc/turn-1",
            "content": "hello world",
            "role": "conversation_turn",
            "agent": "opencode:claude-sonnet",
        }]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == 1
    assert body["skipped"] == 0
    assert body["errors"] == []


def test_ingest_batch(client):
    c, key = client
    records = [
        {
            "source": "opencode",
            "source_key": f"rec_{i}",
            "content": f"turn {i} content",
            "role": "conversation_turn",
        }
        for i in range(5)
    ]
    r = c.post(
        "/ingest",
        headers={"Authorization": f"Bearer {key}"},
        json={"records": records},
    )
    assert r.status_code == 200
    assert r.json()["accepted"] == 5


def test_ingest_dedup(client):
    """Same source_key twice = one accepted, one skipped."""
    c, key = client
    records = [
        {"source": "opencode", "source_key": "dup", "content": "first"},
        {"source": "opencode", "source_key": "dup", "content": "second"},
    ]
    r = c.post(
        "/ingest",
        headers={"Authorization": f"Bearer {key}"},
        json={"records": records},
    )
    body = r.json()
    assert body["accepted"] == 1
    assert body["skipped"] == 1


def test_ingest_applies_privacy_filter(client, cfg_and_key):
    """sk-XXXX secrets should be stripped from content."""
    import json
    c, key = client
    cfg, _ = cfg_and_key
    r = c.post(
        "/ingest",
        headers={"Authorization": f"Bearer {key}"},
        json={"records": [{
            "source": "opencode",
            "source_key": "r1",
            "content": "my key is sk-abcdefghijklmnopqrst",
        }]},
    )
    assert r.status_code == 200
    assert r.json()["accepted"] == 1
    # Find the persisted record file
    raw_dir = Path(cfg.pipeline.data_root) / "raw" / "opencode"
    files = list(raw_dir.glob("r1.json"))
    assert files, f"no file in {raw_dir}"
    d = json.loads(files[0].read_text())
    assert "sk-abc" not in d["content"]
    assert "[REDACTED]" in d["content"]


def test_ingest_invalid_format(client):
    c, key = client
    r = c.post(
        "/ingest",
        headers={"Authorization": f"Bearer {key}"},
        json={"records": [{"no_source_key": True}]},
    )
    # Validation should fail in the loop → ends up in errors
    body = r.json()
    assert body["accepted"] == 0
    assert len(body["errors"]) == 1


def test_ingest_empty_records_rejected(client):
    c, key = client
    r = c.post(
        "/ingest",
        headers={"Authorization": f"Bearer {key}"},
        json={"records": []},
    )
    # Pydantic validation: min_length=1
    assert r.status_code == 422


def test_generate_key_format():
    k = generate_key()
    assert k.startswith("memloom_ingest_")
    assert len(k) >= 30  # prefix + 24 url-safe bytes (32 chars)
