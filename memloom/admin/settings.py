"""Serialize / patch / persist dashboard settings (common knobs only)."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ..config import Config

_MASK = "••••••••"
_UNCHANGED = ""


def settings_public_view(config: Config, config_path: Path | None) -> dict[str, Any]:
    """JSON-safe settings for the UI. Secrets are never returned in cleartext."""
    emb = config.embed
    return {
        "path": str(config_path) if config_path else None,
        "writable": bool(config_path and config_path.parent.exists()),
        "pipeline": {
            "data_root": config.pipeline.data_root,
            "log_level": config.pipeline.log_level,
            "chunk_size": config.pipeline.chunk_size,
        },
        "privacy": {
            "enabled": config.privacy.enabled,
            "strip_patterns": list(config.privacy.strip_patterns),
            "redact_replacement": config.privacy.redact_replacement,
        },
        "denoise": {"enabled": config.denoise.enabled},
        "embed": {
            "enabled": emb.enabled,
            "base_url": emb.base_url,
            "api_key_set": bool(emb.api_key),
            "api_key": _MASK if emb.api_key else _UNCHANGED,
            "model": emb.model,
            "dimension": emb.dimension,
            "batch_size": emb.batch_size,
            "timeout": emb.timeout,
            "max_retries": emb.max_retries,
            "max_chars": emb.max_chars,
            "max_length": emb.max_length,
        },
        "hosts": [h.model_dump() for h in config.hosts],
        "agents": [a.model_dump() for a in config.agents],
        "anythingllm": {
            "enabled": config.anythingllm.enabled,
            "base_url": config.anythingllm.base_url,
            "api_key_set": bool(config.anythingllm.api_key),
            "api_key": _MASK if config.anythingllm.api_key else _UNCHANGED,
            "workspace_slug": config.anythingllm.workspace_slug,
            "auto_embed": config.anythingllm.auto_embed,
        },
    }


def _resolve_secret(new_val: Any, old_val: str) -> str:
    if new_val in (None, _UNCHANGED, _MASK, "***"):
        return old_val
    return str(new_val)


def apply_settings_patch(config: Config, patch: dict[str, Any]) -> tuple[Config, list[str]]:
    """Merge a partial settings patch into a new Config.

    Masked / empty secret fields keep the previous value.
    Returns (new_config, warnings).
    """
    warnings: list[str] = []
    data = config.model_dump()

    if "pipeline" in patch and isinstance(patch["pipeline"], dict):
        for k in ("data_root", "log_level", "chunk_size"):
            if k in patch["pipeline"]:
                data["pipeline"][k] = patch["pipeline"][k]
        new_root = patch["pipeline"].get("data_root")
        if new_root and new_root != config.pipeline.data_root:
            warnings.append("data_root changed — restart memloom serve to remount the store")

    if "privacy" in patch and isinstance(patch["privacy"], dict):
        for k in ("enabled", "strip_patterns", "redact_replacement"):
            if k in patch["privacy"]:
                data["privacy"][k] = patch["privacy"][k]
        warnings.append(
            "privacy changes apply immediately to admin collect; "
            "/ingest keeps the process-start filter until restart"
        )

    if "denoise" in patch and isinstance(patch["denoise"], dict):
        if "enabled" in patch["denoise"]:
            data["denoise"]["enabled"] = patch["denoise"]["enabled"]

    if "embed" in patch and isinstance(patch["embed"], dict):
        emb_patch = dict(patch["embed"])
        emb_patch.pop("api_key_set", None)
        if "api_key" in emb_patch:
            data["embed"]["api_key"] = _resolve_secret(emb_patch.pop("api_key"), config.embed.api_key)
        for k, v in emb_patch.items():
            if k in data["embed"]:
                data["embed"][k] = v

    if "anythingllm" in patch and isinstance(patch["anythingllm"], dict):
        allm = dict(patch["anythingllm"])
        allm.pop("api_key_set", None)
        if "api_key" in allm:
            data["anythingllm"]["api_key"] = _resolve_secret(
                allm.pop("api_key"), config.anythingllm.api_key,
            )
        for k, v in allm.items():
            if k in data["anythingllm"]:
                data["anythingllm"][k] = v

    if "hosts" in patch and isinstance(patch["hosts"], list):
        data["hosts"] = patch["hosts"]

    if "agents" in patch and isinstance(patch["agents"], list):
        data["agents"] = patch["agents"]

    try:
        new_cfg = Config(**data)
    except (ValidationError, TypeError, ValueError) as e:
        raise ValueError(str(e)) from e

    return new_cfg, list(dict.fromkeys(warnings))


def save_config_yaml(config: Config, path: Path) -> None:
    """Atomically write config YAML, keeping a ``.bak`` of the previous file."""
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump(mode="python")
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
