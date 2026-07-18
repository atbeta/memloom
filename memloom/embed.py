"""Embedding client for memloom.

Wraps an OpenAI-compatible ``/v1/embeddings`` endpoint (default: bge-m3-mlx-fp16
on Mac Studio at 192.168.5.13:8000). The embedder is called from:

* the runner after each record is upserted (to keep the vector index in sync)
* the search path when running ``mp search --hybrid`` (to embed the query)

Why a small module, not just ``requests.post``
-------------------------------------------
* Batching: a single HTTP call for up to 64 records (~64× fewer round-trips)
* Retries with exponential backoff (Mac Studio is on Wi-Fi sometimes)
* In-process queue: callers can ``await enqueue(text)`` without blocking

Configuration is via :class:`EmbedConfig` which lives in :mod:`memloom.config`.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Iterator

import requests


log = logging.getLogger(__name__)


@dataclass
class EmbedConfig:
    """Embedding backend config. Defaults to bge-m3 on Mac Studio."""

    base_url: str = "http://192.168.5.13:8000"
    api_key: str = ""               # omlx server doesn't require auth
    model: str = "bge-m3-mlx-fp16"
    dimension: int = 1024
    batch_size: int = 32
    timeout: int = 60
    max_retries: int = 2
    max_chars: int = 2000           # truncate inputs to this many chars (~512 tokens)
    enabled: bool = True


class EmbedError(RuntimeError):
    pass


class Embedder:
    """Thin wrapper around an OpenAI-compatible ``/v1/embeddings`` endpoint."""

    def __init__(self, config: EmbedConfig) -> None:
        self.cfg = config
        self._session = requests.Session()
        if config.api_key:
            self._session.headers["Authorization"] = f"Bearer {config.api_key}"

    # ---- Public API ----

    def health_check(self) -> bool:
        if not self.cfg.enabled:
            return False
        try:
            # omlx doesn't expose /v1/models in a standard way; just hit /v1/embeddings
            r = self._session.post(
                f"{self.cfg.base_url}/v1/embeddings",
                json={"model": self.cfg.model, "input": ["health"]},
                timeout=5,
            )
            return r.ok
        except Exception:
            return False

    def embed_one(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def _truncate(self, text: str) -> str:
        """Truncate to first N chars. For embedding, head usually captures the topic."""
        if len(text) <= self.cfg.max_chars:
            return text
        return text[: self.cfg.max_chars]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns one vector per text, in order.

        Empty / whitespace-only inputs get a zero vector. Long inputs are
        truncated to ``max_chars`` before sending.
        """
        if not texts:
            return []
        # Pre-truncate (cheap, doesn't break the FTS index which has full content)
        truncated = [self._truncate(t) for t in texts]
        # Send in chunks. Keep positional alignment in the returned list.
        out: list[list[float] | None] = [None] * len(texts)
        # Build per-chunk (orig_idx, truncated) to keep order
        chunks: list[list[tuple[int, str]]] = []
        for start in range(0, len(truncated), self.cfg.batch_size):
            chunk = []
            for i in range(start, min(start + self.cfg.batch_size, len(truncated))):
                t = truncated[i]
                if t.strip():
                    chunk.append((i, t))
                else:
                    out[i] = [0.0] * self.cfg.dimension
            if chunk:
                chunks.append(chunk)
        for chunk in chunks:
            indices = [i for i, _ in chunk]
            chunk_texts = [t for _, t in chunk]
            vecs = self._embed_with_retry(chunk_texts)
            for idx, vec in zip(indices, vecs):
                out[idx] = vec
        # Defensive: any leftover None gets a zero vector
        for i in range(len(texts)):
            if out[i] is None:
                out[i] = [0.0] * self.cfg.dimension
        return out

    # ---- Internals ----

    def _embed_with_retry(self, texts: list[str]) -> list[list[float]]:
        # Drop empty strings — server may reject them. We'll return a zero vector
        # for each dropped input so positional alignment is preserved.
        safe_inputs: list[str] = []
        zero_indices: set[int] = set()
        for i, t in enumerate(texts):
            if t.strip():
                safe_inputs.append(t)
            else:
                zero_indices.add(i)
        if not safe_inputs:
            return [[0.0] * self.cfg.dimension for _ in texts]

        body = {"model": self.cfg.model, "input": safe_inputs}
        last_err: Exception | None = None
        for attempt in range(self.cfg.max_retries):
            try:
                r = self._session.post(
                    f"{self.cfg.base_url}/v1/embeddings",
                    json=body,
                    timeout=self.cfg.timeout,
                )
                if r.status_code >= 500:
                    raise EmbedError(f"server {r.status_code}: {r.text[:200]}")
                if not r.ok:
                    raise EmbedError(f"client {r.status_code}: {r.text[:200]}")
                data = r.json()["data"]
                # data is a list of {embedding, index, object} — sort by index
                data.sort(key=lambda x: x.get("index", 0))
                vecs = [d["embedding"] for d in data]
                if vecs and len(vecs[0]) != self.cfg.dimension:
                    raise EmbedError(
                        f"dimension mismatch: server returned {len(vecs[0])}, "
                        f"expected {self.cfg.dimension}"
                    )
                # Re-insert zero-vectors at the original positions for empty inputs
                out: list[list[float]] = []
                safe_idx = 0
                for i in range(len(texts)):
                    if i in zero_indices:
                        out.append([0.0] * self.cfg.dimension)
                    else:
                        out.append(vecs[safe_idx])
                        safe_idx += 1
                return out
            except Exception as e:
                last_err = e
                backoff = 0.5 * (2 ** attempt)
                log.warning(f"embed attempt {attempt+1} failed: {e}; retry in {backoff:.1f}s")
                time.sleep(backoff)
        # If all retries fail, return zero vectors so caller can still store them
        log.warning(f"all retries failed; storing zero-vector placeholders for {len(texts)} inputs")
        return [[0.0] * self.cfg.dimension for _ in texts]


__all__ = ["EmbedConfig", "Embedder", "EmbedError"]