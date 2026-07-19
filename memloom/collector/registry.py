"""Source adapter registry for Hub-bound collectors."""

from __future__ import annotations

from memloom.sync.adapter import SyncAdapter
from memloom.sync.antigravity import AntigravityAdapter
from memloom.sync.codex import CodexAdapter
from memloom.sync.hermes import HermesAdapter
from memloom.sync.kilocode import KiloCodeAdapter
from memloom.sync.opencode import OpenCodeAdapter
from memloom.sync.openclaw_chat import OpenClawChatAdapter
from memloom.sync.openclaw_session import OpenClawSessionAdapter
from memloom.sync.qoder import QoderAdapter
from memloom.sync.librechat import LibreChatSyncAdapter
from memloom.sync.openclaw_workspace import OpenClawWorkspaceAdapter

from .config import SourceConfig

ADAPTER_REGISTRY: dict[str, type[SyncAdapter]] = {
    "opencode": OpenCodeAdapter,
    "codex": CodexAdapter,
    "antigravity": AntigravityAdapter,
    "openclaw_chat": OpenClawChatAdapter,
    "openclaw_session": OpenClawSessionAdapter,
    "openclaw": OpenClawWorkspaceAdapter,
    "qoder": QoderAdapter,
    "hermes": HermesAdapter,
    "kilocode": KiloCodeAdapter,
    "librechat": LibreChatSyncAdapter,
}


def resolve_source_path(src: SourceConfig) -> str:
    """Pick the path/URI field for this source type."""
    if src.type == "librechat":
        return src.mongo_uri or "mongodb://librechat-mongodb:27017/"
    if src.type == "openclaw":
        return src.workspace or src.session_dir or src.db
    return src.db or src.session_dir or src.workspace or src.mongo_uri


def build_adapter(src: SourceConfig) -> SyncAdapter | None:
    cls = ADAPTER_REGISTRY.get(src.type)
    if cls is None:
        return None
    path = resolve_source_path(src)
    if not path and src.type != "librechat":
        return None
    if src.type == "librechat":
        return LibreChatSyncAdapter(path or "mongodb://librechat-mongodb:27017/", database=src.database)
    return cls(path)
