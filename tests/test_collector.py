"""Tests for memloom.collector (Hub-bound)."""
from __future__ import annotations

from pathlib import Path

import pytest

from memloom.collector.config import CollectorConfig, SourceConfig
from memloom.collector.registry import ADAPTER_REGISTRY, build_adapter, resolve_source_path
from memloom.sync.openclaw_workspace import OpenClawWorkspaceAdapter


def test_hub_alias_appends_ingest():
    cfg = CollectorConfig.model_validate(
        {"hub": "http://192.168.5.101:8789", "api_key": "k", "sources": []}
    )
    assert cfg.endpoint == "http://192.168.5.101:8789/ingest"
    assert cfg.hub == "http://192.168.5.101:8789"


def test_hub_already_has_ingest():
    cfg = CollectorConfig.model_validate(
        {"hub": "http://localhost:8789/ingest", "api_key": "k"}
    )
    assert cfg.endpoint == "http://localhost:8789/ingest"


def test_endpoint_compat():
    cfg = CollectorConfig.model_validate(
        {"endpoint": "http://localhost:8789/ingest", "api_key": "k"}
    )
    assert cfg.endpoint.endswith("/ingest")


def test_from_yaml_hub(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "hub: http://hub:8789\napi_key: secret\nsources:\n  - type: opencode\n    db: /tmp/x.db\n"
    )
    cfg = CollectorConfig.from_yaml(p)
    assert cfg.endpoint == "http://hub:8789/ingest"
    assert cfg.sources[0].type == "opencode"


def test_registry_has_librechat_and_openclaw():
    assert "librechat" in ADAPTER_REGISTRY
    assert "openclaw" in ADAPTER_REGISTRY


def test_resolve_librechat_path():
    src = SourceConfig(type="librechat", mongo_uri="mongodb://db:27017/")
    assert resolve_source_path(src) == "mongodb://db:27017/"


def test_openclaw_workspace_extract(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("# memory\nhello world\n")
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "2026-07-19.md").write_text("daily note\n")
    adapter = OpenClawWorkspaceAdapter(str(tmp_path))
    records = adapter.extract()
    assert len(records) >= 2
    sources = {r.role for r in records}
    assert "long_term_memory" in sources
    assert "daily_note" in sources
    assert adapter.get_latest_cursor() > 0


def test_openclaw_workspace_since_filter(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("x\n")
    adapter = OpenClawWorkspaceAdapter(str(tmp_path))
    future = adapter.get_latest_cursor() + 10_000_000
    assert adapter.extract(since_ms=future) == []


def test_build_adapter_openclaw():
    src = SourceConfig(type="openclaw", workspace="/tmp/ws")
    a = build_adapter(src)
    assert a is not None
    assert a.source_type == "openclaw"


def test_build_adapter_librechat():
    src = SourceConfig(type="librechat", mongo_uri="mongodb://localhost:27017/", database="LibreChat")
    a = build_adapter(src)
    assert a is not None
    assert a.source_type == "librechat"
