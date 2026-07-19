"""Hub-bound collector: extract local agent data and POST /ingest."""

from .config import CollectorConfig, SourceConfig
from .registry import ADAPTER_REGISTRY, build_adapter

__all__ = [
    "CollectorConfig",
    "SourceConfig",
    "ADAPTER_REGISTRY",
    "build_adapter",
]
