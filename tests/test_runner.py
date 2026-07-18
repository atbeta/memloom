"""Tests for the runner — full pipeline end-to-end."""
import os

from memloom.config import (
    AgentInstanceConfig,
    Config,
    HostConfig,
    PipelineConfig,
    PrivacyConfig,
)
from memloom.runner import Runner
from memloom.store import RawStore


def test_runner_collects_openclaw(tmp_path, make_workspace):
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir()
    workspace = make_workspace(workspace_root)
    data_root = tmp_path / "data"

    cfg = Config(
        pipeline=PipelineConfig(data_root=str(data_root)),
        privacy=PrivacyConfig(enabled=True, strip_patterns=[r"sk-[A-Za-z0-9_-]{20,}"]),
        hosts=[HostConfig(name="local", transport="local")],
        agents=[AgentInstanceConfig(type="openclaw", host="local", options={"workspace": str(workspace)})],
    )

    # The runner's LocalTransport uses cwd; chdir so default paths resolve to workspace
    old_cwd = os.getcwd()
    try:
        os.chdir(str(workspace))
        runner = Runner(cfg)
        summaries = runner.collect_once()
    finally:
        os.chdir(old_cwd)

    assert len(summaries) == 1
    s = summaries[0]
    assert s.source == "openclaw"
    assert s.new_records >= 3

    store = RawStore(str(data_root))
    stats = store.stats()
    assert stats["total"] >= 3
    assert stats["by_source"]["openclaw"] >= 3

    # Verify redaction actually happened
    md_files = list((data_root / "raw" / "openclaw").glob("*.md"))
    assert md_files
    full_md = "\n".join(p.read_text(encoding="utf-8") for p in md_files)
    assert "sk-abcdef" not in full_md
    assert "[REDACTED]" in full_md


def test_runner_idempotent(tmp_path, make_workspace):
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir()
    workspace = make_workspace(workspace_root)
    data_root = tmp_path / "data"
    cfg = Config(
        pipeline=PipelineConfig(data_root=str(data_root)),
        privacy=PrivacyConfig(enabled=False),
        hosts=[HostConfig(name="local", transport="local")],
        agents=[AgentInstanceConfig(type="openclaw", host="local", options={"workspace": str(workspace)})],
    )
    old_cwd = os.getcwd()
    try:
        os.chdir(str(workspace))
        runner = Runner(cfg)
        s1 = runner.collect_once()
        s2 = runner.collect_once()
    finally:
        os.chdir(old_cwd)

    assert s1[0].new_records >= 3
    # Second run: nothing should change → new_records == 0
    assert s2[0].new_records == 0


def test_runner_search_after_collect(tmp_path, make_workspace):
    workspace_root = tmp_path / "ws"
    workspace_root.mkdir()
    workspace = make_workspace(workspace_root)
    data_root = tmp_path / "data"
    cfg = Config(
        pipeline=PipelineConfig(data_root=str(data_root)),
        privacy=PrivacyConfig(enabled=False),
        hosts=[HostConfig(name="local", transport="local")],
        agents=[AgentInstanceConfig(type="openclaw", host="local", options={"workspace": str(workspace)})],
    )
    old_cwd = os.getcwd()
    try:
        os.chdir(str(workspace))
        Runner(cfg).collect_once()
    finally:
        os.chdir(old_cwd)

    store = RawStore(str(data_root))
    hits = store.search("memory-pipeline")
    assert hits
    assert hits[0]["source"] == "openclaw"
