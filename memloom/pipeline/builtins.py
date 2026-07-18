"""Pre-built pipeline steps wrapping existing transforms."""

from . import Deduper, Denoiser, PrivacyFilter, tag_record
from .chunk import ConversationChunker
from .step import PipelineStep, register


# ── Privacy ──────────────────────────────────────────────────────────────────

@register("privacy")
class PrivacyStep(PipelineStep):
    name = "privacy"
    order = 10

    def __init__(self, patterns: list[str] | None = None, replacement: str = "[REDACTED]"):
        self._filter = PrivacyFilter(patterns or [], replacement=replacement)

    def process(self, record):
        rec, _ = self._filter.filter_record(record)
        if rec.content.strip():
            yield rec
        # else: skip


# ── Denoise ──────────────────────────────────────────────────────────────────

@register("denoise")
class DenoiseStep(PipelineStep):
    name = "denoise"
    order = 20

    def __init__(self):
        self._denoiser = Denoiser()

    def process(self, record):
        rec, _ = self._denoiser.denoise_record(record)
        if rec.content.strip():
            yield rec


# ── Chunker ──────────────────────────────────────────────────────────────────

@register("chunker")
class ChunkerStep(PipelineStep):
    name = "chunker"
    order = 30

    def __init__(self, target_size: int = 8192):
        self._chunker = ConversationChunker(target_size=target_size)

    def process(self, record):
        yield from self._chunker.process(record)


# ── Tag ──────────────────────────────────────────────────────────────────────

@register("tag")
class TagStep(PipelineStep):
    name = "tag"
    order = 50

    def process(self, record):
        yield tag_record(record)


# ── Dedup ────────────────────────────────────────────────────────────────────

@register("dedup")
class DedupStep(PipelineStep):
    name = "dedup"
    order = 60

    def __init__(self):
        self._deduper = Deduper()

    def process(self, record):
        if self._deduper.is_new(record):
            yield record
        # else: skip duplicate
