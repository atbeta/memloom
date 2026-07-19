"""CollectorConfig — YAML for a Hub-bound collector."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class SourceConfig(BaseModel):
    type: str = ""
    db: str = ""
    session_dir: str = ""
    workspace: str = ""
    mongo_uri: str = ""
    database: str = "LibreChat"


class CollectorConfig(BaseModel):
    """Bind this collector to a Hub and list local sources."""

    hub: str = ""
    endpoint: str = "http://localhost:8789/ingest"  # sync compat alias
    api_key: str = ""
    batch_size: int = Field(default=500, ge=1, le=10000)
    sources: list[SourceConfig] = Field(default_factory=list)
    state_dir: Path = Path("~/.memloom-collector").expanduser()
    skip_embed: bool = False
    interval: int = Field(default=300, ge=1)  # seconds for --loop

    @model_validator(mode="before")
    @classmethod
    def _alias_hub(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        raw = dict(data)
        hub = (raw.get("hub") or "").strip()
        endpoint = (raw.get("endpoint") or "").strip()
        if hub:
            ep = hub.rstrip("/")
            if not ep.endswith("/ingest"):
                ep = f"{ep}/ingest"
            raw["endpoint"] = ep
            raw["hub"] = hub
        elif endpoint:
            raw["endpoint"] = endpoint
            raw["hub"] = endpoint
        return raw

    @model_validator(mode="after")
    def _resolve_api_key(self) -> CollectorConfig:
        if not self.api_key:
            self.api_key = os.environ.get("MEMLOOM_INGEST_KEY") or ""
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> CollectorConfig:
        import yaml

        with open(path) as f:
            raw = yaml.safe_load(f) or {}
        # Prefer new default state_dir; allow legacy ~/.memloom-sync if set
        if "state_dir" not in raw and Path("~/.memloom-sync").expanduser().exists():
            if not Path("~/.memloom-collector").expanduser().exists():
                raw["state_dir"] = str(Path("~/.memloom-sync").expanduser())
        return cls.model_validate(raw)


# Backward-compat names used by memloom.sync
SyncConfig = CollectorConfig
