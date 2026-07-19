"""Configuration loader (YAML + pydantic-settings).

One config file: ``config/memory-pipeline.yaml`` (or wherever you point it).
Sensible defaults baked in so a fresh checkout can run with zero config.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

# ---------- Config sub-sections -------------------------------------------

class PipelineConfig(BaseModel):
    data_root: str = "./data"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    steps: list[str] = Field(default_factory=list)  # v0.6: explicit step ordering
    chunk_size: int = Field(default=8192, ge=1024)   # max chars per chunk


class PrivacyConfig(BaseModel):
    """What to strip before writing records to disk.

    The intent: keep secrets/PII out of the local knowledge base permanently.
    Company project visibility tagging is intentionally NOT in v0.1 (per design).
    """
    enabled: bool = True
    strip_patterns: list[str] = Field(
        default_factory=lambda: _DEFAULT_STRIP_PATTERNS
    )
    redact_replacement: str = "[REDACTED]"


class HostConfig(BaseModel):
    name: str
    transport: Literal["local", "ssh"] = "local"
    ssh_host: str | None = None
    ssh_user: str | None = None
    ssh_port: int = 22
    ssh_key_file: str | None = None
    ssh_password: str | None = None  # discouraged; prefer key_file


class AgentInstanceConfig(BaseModel):
    """One configured (agent, host) pair."""
    type: str                 # "openclaw" | "claude_code" | ...
    host: str = "local"
    enabled: bool = True
    options: dict[str, Any] = Field(default_factory=dict)


class AnythingLLMConfig(BaseModel):
    """AnythingLLM vector backend config."""
    enabled: bool = False
    base_url: str = "http://ai-knowledge:3001"
    api_key: str = ""
    workspace_slug: str = "ai-knowledge"
    auto_embed: bool = True


class EmbedConfig(BaseModel):
    """Local embedding backend (used for hybrid search via sqlite-vec)."""
    enabled: bool = True
    base_url: str = "http://192.168.5.13:8000"
    api_key: str = ""
    model: str = "bge-m3-mlx-fp16"
    dimension: int = 1024
    batch_size: int = 32
    timeout: int = 120
    max_retries: int = 3
    max_chars: int = 2000
    max_length: int = 2048


class DenoiseConfig(BaseModel):
    """Content denoising — strip tool output JSON wrapping etc."""
    enabled: bool = True


class Config(BaseModel):
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    denoise: DenoiseConfig = Field(default_factory=DenoiseConfig)
    hosts: list[HostConfig] = Field(default_factory=list)
    agents: list[AgentInstanceConfig] = Field(default_factory=list)
    anythingllm: AnythingLLMConfig = Field(default_factory=AnythingLLMConfig)
    embed: EmbedConfig = Field(default_factory=EmbedConfig)

    # ---- Helpers ----

    def host(self, name: str) -> HostConfig | None:
        for h in self.hosts:
            if h.name == name:
                return h
        return None

    def agents_by_type(self, agent_type: str) -> list[AgentInstanceConfig]:
        return [a for a in self.agents if a.type == agent_type and a.enabled]

    def all_enabled_agents(self) -> list[AgentInstanceConfig]:
        return [a for a in self.agents if a.enabled]


# ---------- Default secret patterns ---------------------------------------

_DEFAULT_STRIP_PATTERNS = [
    # OpenAI / OpenAI-compatible
    r"sk-[A-Za-z0-9_\-]{20,}",
    r"sk-proj-[A-Za-z0-9_\-]{20,}",
    # Anthropic
    r"sk-ant-[A-Za-z0-9_\-]{20,}",
    # GitHub
    r"ghp_[A-Za-z0-9]{36,}",
    r"gho_[A-Za-z0-9]{36,}",
    r"ghu_[A-Za-z0-9]{36,}",
    r"ghs_[A-Za-z0-9]{36,}",
    r"ghr_[A-Za-z0-9]{36,}",
    r"github_pat_[A-Za-z0-9_]{60,}",
    # AWS
    r"AKIA[0-9A-Z]{16}",
    r"ASIA[0-9A-Z]{16}",
    # Google API
    r"AIza[0-9A-Za-z\-_]{35}",
    # Slack
    r"xox[abprs]-[A-Za-z0-9\-]{10,}",
    # Generic bearer tokens (last resort; keep narrow to avoid false positives)
    r"Bearer\s+[A-Za-z0-9\-._~+/]{20,}=*",
]


# ---------- Loader --------------------------------------------------------

DEFAULT_CONFIG_PATHS = [
    "./config/memloom.yaml",
    "./memloom.yaml",
    "./config/memory-pipeline.yaml",
    "./memory-pipeline.yaml",
    "~/.config/memloom/config.yaml",
    "~/.config/memory-pipeline/config.yaml",
]


def find_config(explicit: str | os.PathLike | None = None) -> Path | None:
    """Locate a config file by explicit path, env var, or default search order."""
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.exists() else None
    env = os.environ.get("MEMORY_PIPELINE_CONFIG")
    if env:
        p = Path(env).expanduser()
        return p if p.exists() else None
    for cand in DEFAULT_CONFIG_PATHS:
        p = Path(cand).expanduser()
        if p.exists():
            return p
    return None


def load_config(path: str | os.PathLike | None = None) -> Config:
    """Load + validate config. Missing file → defaults."""
    p = find_config(path)
    if p is None:
        return Config()
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Config(**raw)


__all__ = [
    "Config",
    "PipelineConfig",
    "PrivacyConfig",
    "HostConfig",
    "AgentInstanceConfig",
    "AnythingLLMConfig",
    "EmbedConfig",
    "load_config",
    "find_config",
]
