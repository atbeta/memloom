"""Built-in agent collectors. Plugin architecture: drop a new file here."""
from .base import AgentAdapter, CollectorContext
from .claude_code import ClaudeCodeAdapter
from .codex import CodexAdapter
from .generic_jsonl import GenericJSONLAdapter
from .openclaw import OpenClawAdapter
from .openclaw_sessions import OpenClawSessionAdapter

_REGISTRY: dict[str, type[AgentAdapter]] = {
    OpenClawAdapter.name: OpenClawAdapter,
    OpenClawSessionAdapter.name: OpenClawSessionAdapter,
    ClaudeCodeAdapter.name: ClaudeCodeAdapter,
    CodexAdapter.name: CodexAdapter,
    GenericJSONLAdapter.name: GenericJSONLAdapter,
}


def get_adapter(agent_type: str, options: dict | None = None) -> AgentAdapter:
    cls = _REGISTRY.get(agent_type)
    if cls is None:
        raise KeyError(
            f"Unknown agent type: {agent_type!r}. "
            f"Known: {sorted(_REGISTRY.keys())}"
        )
    return cls(options=options)


def register(agent_type: str, cls: type[AgentAdapter]) -> None:
    """Allow external packages to register new agent adapters."""
    _REGISTRY[agent_type] = cls


def known_agents() -> list[str]:
    return sorted(_REGISTRY.keys())


__all__ = [
    "AgentAdapter",
    "CollectorContext",
    "OpenClawAdapter",
    "OpenClawSessionAdapter",
    "ClaudeCodeAdapter",
    "CodexAdapter",
    "GenericJSONLAdapter",
    "get_adapter",
    "register",
    "known_agents",
]
