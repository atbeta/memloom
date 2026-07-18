"""SyncConfig — YAML-driven config for memloom-sync."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class SourceConfig(BaseModel):
    type: str = ""  # "opencode" | "codex" | "antigravity" | "qoder" | "kilocode"
    db: str = ""
    session_dir: str = ""  # antigravity: brain_dir; kilocode: tasks_dir


class SyncConfig(BaseModel):
    endpoint: str = "http://localhost:8789/ingest"
    api_key: str = ""
    batch_size: int = Field(default=500, ge=1, le=10000)
    sources: list[SourceConfig] = Field(default_factory=list)
    state_dir: Path = Path("~/.memloom-sync").expanduser()
    skip_embed: bool = False

    @classmethod
    def from_yaml(cls, path: str | Path) -> SyncConfig:
        import yaml  # soft dependency — only needed when reading config

        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        return cls.model_validate(raw)
