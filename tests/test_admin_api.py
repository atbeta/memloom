"""Tests for the memloom admin HTTP API."""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from memloom.config import Config, EmbedConfig, HostConfig, PipelineConfig, PrivacyConfig
from memloom.ingest_server import create_app
from memloom.records import MemoryRecord
from memloom.store import RawStore


@pytest.fixture
def cfg_and_key():
    key = "test_key_" + "x" * 32
    os.environ["MEMLOOM_INGEST_KEY"] = key
    os.environ.pop("MEMLOOM_ADMIN_KEY", None)
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(
            pipeline=PipelineConfig(data_root=tmp),
            privacy=PrivacyConfig(enabled=True, strip_patterns=[r"sk-[a-z]{20}"]),
            hosts=[HostConfig(name="local", transport="local")],
            embed=EmbedConfig(enabled=False),
        )
        yield cfg, key
    os.environ.pop("MEMLOOM_INGEST_KEY", None)
    os.environ.pop("MEMLOOM_ADMIN_KEY", None)


@pytest.fixture
def client(cfg_and_key):
    cfg, key = cfg_and_key
    app = create_app(cfg)
    return TestClient(app), key


def test_admin_requires_auth(client):
    c, _ = client
    assert c.get("/api/admin/overview").status_code == 401


def test_admin_overview_ok(client):
    c, key = client
    r = c.get("/api/admin/overview", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200
    body = r.json()
    assert "total" in body
    assert "by_source" in body
    assert "vectors" in body
    assert "runs" in body
    assert "data_root" in body
    assert "embed_enabled" in body
    assert "agent_count" in body


def test_admin_runs(client):
    c, key = client
    r = c.get("/api/admin/runs", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_admin_search_and_get(client, cfg_and_key):
    c, key = client
    cfg, _ = cfg_and_key
    store = RawStore(cfg.pipeline.data_root)
    rec = MemoryRecord(
        source="opencode",
        source_key="s1",
        content="alpha beta gamma",
        role="note",
    )
    store.upsert(rec)
    hdr = {"Authorization": f"Bearer {key}"}
    s = c.get("/api/admin/search", params={"q": "alpha", "hybrid": "false"}, headers=hdr)
    assert s.status_code == 200
    assert any(x["id"] == rec.id for x in s.json())
    g = c.get(f"/api/admin/records/{rec.id}", headers=hdr)
    assert g.status_code == 200
    assert g.json()["record"]["content"] == "alpha beta gamma"
    assert c.get("/api/admin/records/rec_nope", headers=hdr).status_code == 404


def test_admin_key_override(cfg_and_key):
    cfg, ingest_key = cfg_and_key
    admin_key = "admin_key_" + "y" * 32
    os.environ["MEMLOOM_ADMIN_KEY"] = admin_key
    app = create_app(cfg)
    c = TestClient(app)
    assert c.get(
        "/api/admin/overview",
        headers={"Authorization": f"Bearer {ingest_key}"},
    ).status_code == 401
    assert c.get(
        "/api/admin/overview",
        headers={"Authorization": f"Bearer {admin_key}"},
    ).status_code == 200
