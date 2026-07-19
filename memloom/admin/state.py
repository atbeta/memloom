"""Mutable runtime state shared by admin routes."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..embed import EmbedConfig, Embedder
from ..store import RawStore


@dataclass
class AdminState:
    config: Config
    store: RawStore
    embedder: Embedder | None = None
    config_path: Path | None = None
    notes: list[str] = field(default_factory=list)

    def rebuild_embedder(self) -> None:
        emb = getattr(self.config, "embed", None)
        if emb is None or not emb.enabled:
            self.embedder = None
            return
        try:
            self.embedder = Embedder(EmbedConfig(
                base_url=emb.base_url,
                api_key=emb.api_key,
                model=emb.model,
                dimension=emb.dimension,
                batch_size=emb.batch_size,
                timeout=emb.timeout,
                max_retries=emb.max_retries,
                enabled=True,
            ))
        except Exception:
            self.embedder = None
