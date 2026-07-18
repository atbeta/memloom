"""Shared test fixtures."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def make_workspace():
    """Factory: create a fake OpenClaw-style workspace at any tmp dir.
    Returns the workspace root path."""
    def _make(root: Path) -> Path:
        (root / "MEMORY.md").write_text(
            "# Long-term memory\n\nUser is Beta, located in Shanghai.\n"
            "API key: sk-abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG\n",
            encoding="utf-8",
        )
        (root / "memory").mkdir(exist_ok=True)
        (root / "memory" / "2026-07-18.md").write_text(
            "# 2026-07-18\n\n- Worked on memory-pipeline\n"
            "- Secret: ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
            encoding="utf-8",
        )
        (root / "SOUL.md").write_text("# Soul\n\nBe helpful.\n", encoding="utf-8")
        return root
    return _make


@pytest.fixture
def make_claude_session():
    """Factory: write a Claude Code session JSONL at any path."""
    def _make(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps({
                "type": "user",
                "message": {"role": "user", "content": "Hello, what can you do?"},
                "timestamp": "2026-07-18T10:00:00Z",
                "sessionId": path.stem,
                "cwd": "/Users/beta/projects/myproj",
                "uuid": "u1",
            }),
            json.dumps({
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I can read files and run commands."},
                        {"type": "tool_use", "name": "read_file", "input": {"path": "/tmp/x"}},
                    ],
                },
                "timestamp": "2026-07-18T10:00:05Z",
                "sessionId": path.stem,
                "cwd": "/Users/beta/projects/myproj",
                "uuid": "a1",
            }),
            "this is not valid json\n",
            json.dumps({
                "type": "user",
                "message": {"role": "user", "content": "Thanks"},
                "timestamp": "2026-07-18T10:00:10Z",
                "sessionId": path.stem,
                "cwd": "/Users/beta/projects/myproj",
                "uuid": "u2",
            }),
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path
    return _make


@pytest.fixture
def make_codex_session():
    """Factory: write a Codex rollout JSONL at any path."""
    def _make(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps({
                "timestamp": "2026-07-18T10:00:00Z",
                "type": "message",
                "cwd": "/Users/beta/projects/myproj",
                "payload": {"role": "user", "content": "Run the tests"},
            }),
            json.dumps({
                "timestamp": "2026-07-18T10:00:02Z",
                "type": "message",
                "cwd": "/Users/beta/projects/myproj",
                "payload": {"role": "assistant", "content": "Running tests..."},
            }),
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path
    return _make
