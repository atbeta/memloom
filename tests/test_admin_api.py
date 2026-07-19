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


def test_admin_settings_get_and_patch(cfg_and_key, tmp_path):
    from pathlib import Path

    import yaml

    cfg, key = cfg_and_key
    cfg_path = tmp_path / "memloom.yaml"
    cfg_path.write_text(
        yaml.safe_dump(cfg.model_dump(mode="python"), sort_keys=False),
        encoding="utf-8",
    )
    # Point data_root at the same temp store used by cfg
    app = create_app(cfg, config_path=cfg_path)
    c = TestClient(app)
    hdr = {"Authorization": f"Bearer {key}"}

    g = c.get("/api/admin/settings", headers=hdr)
    assert g.status_code == 200
    body = g.json()
    assert body["writable"] is True
    assert body["embed"]["api_key"] in ("", "••••••••")

    p = c.patch(
        "/api/admin/settings",
        headers=hdr,
        json={"pipeline": {"log_level": "DEBUG"}, "denoise": {"enabled": False}},
    )
    assert p.status_code == 200
    assert p.json()["pipeline"]["log_level"] == "DEBUG"
    assert p.json()["denoise"]["enabled"] is False
    saved = yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8"))
    assert saved["pipeline"]["log_level"] == "DEBUG"
    assert cfg_path.with_suffix(cfg_path.suffix + ".bak").exists()


def test_admin_settings_patch_requires_path(client):
    c, key = client
    r = c.patch(
        "/api/admin/settings",
        headers={"Authorization": f"Bearer {key}"},
        json={"denoise": {"enabled": False}},
    )
    assert r.status_code == 400


def test_admin_collect_action(client):
    c, key = client
    r = c.post(
        "/api/admin/actions/collect",
        headers={"Authorization": f"Bearer {key}"},
        json={},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["runs"], list)


def test_admin_quarantine_roundtrip(client, cfg_and_key):
    c, key = client
    cfg, _ = cfg_and_key
    store = RawStore(cfg.pipeline.data_root)
    rec = MemoryRecord(
        source="opencode",
        source_key="q1",
        content="quarantine me please now",
        role="note",
    )
    store.upsert(rec)
    hdr = {"Authorization": f"Bearer {key}"}

    add = c.post(
        "/api/admin/quarantine/add",
        headers=hdr,
        json={"record_ids": [rec.id], "reason": "test"},
    )
    assert add.status_code == 200
    assert rec.id in add.json()["moved"]
    assert store.get_record(rec.id) is None

    listed = c.get("/api/admin/quarantine", headers=hdr)
    assert listed.status_code == 200
    assert any(x.get("id") == rec.id for x in listed.json())

    restore = c.post(
        "/api/admin/quarantine/restore",
        headers=hdr,
        json={"record_ids": [rec.id]},
    )
    assert restore.status_code == 200
    assert rec.id in restore.json()["moved"]
