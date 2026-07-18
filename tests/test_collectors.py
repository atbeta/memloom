"""Tests for agent collectors."""
import json

from memloom.collectors import (
    ClaudeCodeAdapter,
    CodexAdapter,
    GenericJSONLAdapter,
    OpenClawAdapter,
    get_adapter,
    known_agents,
)
from memloom.collectors.base import CollectorContext


def _ctx(transport, run_id="test_run", last_watermarks=None):
    return CollectorContext(transport=transport, run_id=run_id, last_watermarks=last_watermarks or {})


# ---------- registry ----------

def test_registry_has_four_adapters():
    assert set(known_agents()) == {"openclaw", "openclaw_session", "claude_code", "codex", "generic_jsonl"}


def test_get_adapter_unknown_raises():
    import pytest
    with pytest.raises(KeyError):
        get_adapter("not_a_real_agent")


# ---------- openclaw ----------

def test_openclaw_adapter_picks_up_files(tmp_path, make_workspace):
    workspace = make_workspace(tmp_path)
    from memloom.transport import LocalTransport
    t = LocalTransport(root=str(workspace))

    adapter = OpenClawAdapter(options={"workspace": str(workspace)})
    sources = adapter.discover(t)
    paths = {s.path for s in sources}
    assert any(p.endswith("MEMORY.md") for p in paths)
    assert any(p.endswith("2026-07-18.md") for p in paths)

    records = []
    for src in sources:
        for rec, wm in adapter.pull(src, _ctx(t)):
            records.append(rec)

    roles = {r.role for r in records}
    assert "long_term_memory" in roles
    assert "daily_note" in roles
    full = "\n".join(r.content for r in records)
    # Adapter doesn't redact — pipeline does
    assert "sk-abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG" in full


# ---------- claude_code ----------

def test_claude_code_parses_jsonl(tmp_path, make_claude_session):
    session = make_claude_session(tmp_path / "session-abc.jsonl")
    from memloom.transport import LocalTransport
    t = LocalTransport(root=str(tmp_path))
    adapter = ClaudeCodeAdapter(options={"paths": [str(session.name)]})

    sources = adapter.discover(t)
    assert len(sources) >= 1

    recs = []
    for src in sources:
        for rec, wm in adapter.pull(src, _ctx(t)):
            recs.append(rec)

    # 3 valid lines + 1 _file_summary = 4 records total
    real_recs = [r for r in recs if not r.role.startswith("_")]
    assert len(real_recs) == 3

    roles = [r.role for r in real_recs]
    assert roles.count("user") == 2
    assert roles.count("assistant") == 1

    # Tool use rendered correctly
    assistant_rec = next(r for r in real_recs if r.role == "assistant")
    assert "[tool_use:read_file]" in assistant_rec.content
    assert "I can read files" in assistant_rec.content

    # Project inferred from cwd
    assert all(r.project == "myproj" for r in real_recs if r.project)


# ---------- codex ----------

def test_codex_parses_jsonl(tmp_path, make_codex_session):
    session = make_codex_session(tmp_path / "rollout-2026-07-18T10-00-00-abc.jsonl")
    from memloom.transport import LocalTransport
    t = LocalTransport(root=str(tmp_path))
    adapter = CodexAdapter(options={"paths": [str(session.name)]})

    sources = adapter.discover(t)
    assert len(sources) == 1

    recs = []
    for src in sources:
        for rec, wm in adapter.pull(src, _ctx(t)):
            recs.append(rec)

    real_recs = [r for r in recs if not r.role.startswith("_")]
    assert len(real_recs) == 2
    assert real_recs[0].role == "user"
    assert real_recs[1].role == "assistant"
    assert all(r.project == "myproj" for r in real_recs)


# ---------- generic_jsonl ----------

def test_generic_jsonl_picks_up_any_jsonl(tmp_path):
    from memloom.transport import LocalTransport
    d = tmp_path / "logs"
    d.mkdir()
    p = d / "events.jsonl"
    p.write_text("\n".join([
        json.dumps({"role": "user", "content": "hello", "agent": "mystery_bot"}),
        json.dumps({"role": "assistant", "content": "hi back", "agent": "mystery_bot"}),
    ]))
    t = LocalTransport(root=str(tmp_path))
    adapter = GenericJSONLAdapter(options={"paths": ["logs/*.jsonl"]})
    sources = adapter.discover(t)
    assert len(sources) == 1
    recs = list(adapter.pull(sources[0], _ctx(t)))
    assert len(recs) == 2
    assert recs[0][0].role == "user"
    assert recs[0][0].agent == "mystery_bot"


# ---------- idempotency ----------

def test_openclaw_adapter_skips_unchanged(tmp_path, make_workspace):
    workspace = make_workspace(tmp_path)
    from memloom.transport import LocalTransport
    t = LocalTransport(root=str(workspace))
    adapter = OpenClawAdapter(options={"workspace": str(workspace)})

    sources = adapter.discover(t)
    src = next(s for s in sources if s.path.endswith("MEMORY.md"))

    # First pull → 1 record
    recs1 = list(adapter.pull(src, _ctx(t)))
    assert any(r.role == "long_term_memory" for r, _ in recs1)

    # Second pull with watermark → only skip marker, no new record
    recs2 = list(adapter.pull(src, _ctx(t, run_id="run2", last_watermarks={src.source_key: recs1[-1][1]})))
    real = [r for r, _ in recs2 if r.role != "_skip_marker"]
    assert real == []
