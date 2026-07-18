"""Conversation chunker — splits large records at turn boundaries.

Large records (500K+ chars from Hermes) produce poor embeddings because
the entire document is chunked arbitrarily. This step splits at natural
## user / ## assistant boundaries to create coherent, embeddable chunks.

Config: ``pipeline.chunker.target_size`` (default 8192 chars).
"""

from __future__ import annotations

from ..records import MemoryRecord
from .step import PipelineStep


class ConversationChunker(PipelineStep):
    name = "chunker"
    order = 45  # after denoise(40), before tag(50)

    def __init__(self, target_size: int = 8192):
        self.target_size = target_size

    def process(self, record):
        content = record.content
        if not content or len(content) <= self.target_size:
            yield record  # pass through
            return

        chunks = self._split(content, self.target_size)
        if len(chunks) <= 1:
            yield record
            return

        for i, chunk in enumerate(chunks):
            yield MemoryRecord(
                source=record.source,
                source_key=f"{record.source_key}#chunk{i+1}",
                id="",
                agent=record.agent,
                project=record.project,
                visibility=record.visibility,
                captured_at=record.captured_at,
                occurred_at=record.occurred_at,
                duration_ms=record.duration_ms,
                role=record.role,
                content=chunk,
                raw_meta={**record.raw_meta, "chunk_index": i + 1, "chunk_total": len(chunks),
                          "original_id": record.id},
                raw_ref=record.raw_ref,
                tags=record.tags,
            )

    @staticmethod
    def _split(text: str, target: int) -> list[str]:
        """Split at ## user / ## assistant boundaries."""
        # Find turn boundaries
        sections = []
        current = []
        current_len = 0
        lines = text.split("\n")

        for line in lines:
            stripped = line.strip()
            # Section boundary: ## user or ## assistant
            is_boundary = (stripped.startswith("## user") or
                          stripped.startswith("## assistant") or
                          stripped.startswith("## User") or
                          stripped.startswith("## Assistant"))

            if is_boundary and current_len > target * 0.3:
                # Start new chunk
                sections.append("\n".join(current))
                current = [line]
                current_len = len(line)
            else:
                current.append(line)
                current_len += len(line) + 1

        if current:
            sections.append("\n".join(current))

        # Merge too-small chunks with neighbors
        merged = _merge_small(sections, target)
        return merged


def _merge_small(chunks: list[str], target: int) -> list[str]:
    """Merge chunks smaller than target/3 with adjacent ones."""
    result = []
    buffer = ""
    for chunk in chunks:
        if len(chunk) < target // 3 and result:
            result[-1] = result[-1] + "\n\n" + chunk
        elif buffer:
            buffer = buffer + "\n\n" + chunk
            if len(buffer) >= target // 2:
                result.append(buffer)
                buffer = ""
        elif len(chunk) < target // 3:
            buffer = chunk
        else:
            result.append(chunk)
    if buffer:
        if result:
            result[-1] = result[-1] + "\n\n" + buffer
        else:
            result.append(buffer)
    return result
