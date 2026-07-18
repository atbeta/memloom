"""Pluggable pipeline — chainable transform steps.

Each step receives a record and yields 0+ records:
  - yield 0 records = skip (filter out noise, duplicates, empty)
  - yield 1 record  = pass (normal transform)
  - yield N records = split (chunker)

Steps are loaded from config and run in configured order.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Generator

from ..records import MemoryRecord


# ── Step interface ───────────────────────────────────────────────────────────

class PipelineStep(ABC):
    """A pluggable pipeline step.

    name: stable identifier matching config.
    order: lower = earlier in the chain.
    """

    name: str = ""
    order: int = 100

    @abstractmethod
    def process(self, record: MemoryRecord) -> Generator[MemoryRecord, None, None]:
        """Process one record, yielding 0+ records downstream."""


# ── Pluggable pipeline ───────────────────────────────────────────────────────

@dataclass
class PluggablePipeline:
    steps: list[PipelineStep] = field(default_factory=list)

    def run(self, record: MemoryRecord) -> Generator[MemoryRecord, None, None]:
        """Run all steps. Each step's output feeds into the next."""
        records = [record]
        for step in self.steps:
            next_batch = []
            for r in records:
                for out in step.process(r):
                    next_batch.append(out)
            records = next_batch
            if not records:
                break
        yield from records

    def add(self, step: PipelineStep) -> None:
        self.steps.append(step)
        self.steps.sort(key=lambda s: s.order)


# ── Step registry ────────────────────────────────────────────────────────────

# Maps config names to step classes. External code adds their steps here.
REGISTRY: dict[str, type[PipelineStep]] = {}


def register(name: str):
    """Decorator to register a PipelineStep."""
    def decorator(cls):
        REGISTRY[name] = cls
        return cls
    return decorator
