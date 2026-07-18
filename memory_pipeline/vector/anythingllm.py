"""AnythingLLM pusher.

Strategy
--------
1. Take a list of MemoryRecords
2. Render each as markdown with metadata header
3. POST each one to ``/api/v1/document/raw-text?workspaceSlug={slug}``
4. After the batch, POST ``/api/v1/workspace/{slug}/update-embeddings`` once

Why one record per push
-----------------------
- Granular provenance in AnythingLLM's UI (each doc shows source/agent/date)
- Easy to delete a single bad record without nuking the batch
- Idempotency: each push uses a deterministic title derived from source_key, so
  re-pushing the same record creates a new doc but with the same name → we
  detect duplicates via the docs index and skip.

Auth
----
API key goes in ``Authorization: Bearer <key>`` header. Key + endpoint + slug
come from config (or env var).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Iterable

import requests

from ..records import MemoryRecord


@dataclass
class AnythingLLMConfig:
    base_url: str = "http://ai-knowledge:3001"   # Docker-internal hostname
    api_key: str = ""
    workspace_slug: str = "ai-knowledge"
    timeout: int = 30
    auto_embed: bool = True                      # trigger update-embeddings after each batch


class AnythingLLMPusher:
    def __init__(self, config: AnythingLLMConfig) -> None:
        self.cfg = config
        if not config.api_key:
            raise ValueError("AnythingLLM api_key is required")
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {config.api_key}",
            "Accept": "application/json",
        })

    # ---- Public API ----

    def health_check(self) -> bool:
        try:
            r = self._session.get(f"{self.cfg.base_url}/api/ping", timeout=5)
            return r.ok and (r.json().get("online") is True)
        except Exception:
            return False

    def list_documents(self) -> list[dict]:
        """List all docs in the workspace. Used for dedup."""
        r = self._session.get(
            f"{self.cfg.base_url}/api/v1/workspace/{self.cfg.workspace_slug}",
            timeout=self.cfg.timeout,
        )
        r.raise_for_status()
        ws = r.json()["workspace"][0]
        return ws.get("documents", []) or []

    def push_records(
        self,
        records: Iterable[MemoryRecord],
        skip_duplicates: bool = True,
    ) -> dict:
        """Push records. Returns counts.

        Dedup strategy: AnythingLLM appends a UUID to whatever filename we
        suggest via title. We compare by *prefix* (raw-<slug>-) and by the
        metadata.url we previously sent. Either match counts as duplicate.
        """
        existing_prefixes: set[str] = set()
        existing_urls: set[str] = set()
        if skip_duplicates:
            try:
                for d in self.list_documents():
                    fn = d.get("filename", "")
                    if fn:
                        # Strip the trailing -{uuid}.json to get a stable prefix
                        # Filenames look like: raw-<slug>-<uuid>.json
                        prefix = _strip_uuid(fn)
                        if prefix:
                            existing_prefixes.add(prefix.lower())
                    # Metadata is JSON-encoded in workspace_documents.metadata
                    meta_raw = d.get("metadata", "")
                    if meta_raw:
                        try:
                            meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
                            url = meta.get("url", "")
                            if url and url.startswith("memory-pipeline://"):
                                existing_urls.add(url)
                        except (json.JSONDecodeError, TypeError):
                            pass
            except Exception:
                pass

        pushed = 0
        skipped = 0
        errors: list[str] = []
        for rec in records:
            title = _title_for(rec)
            url = f"memory-pipeline://{rec.source}/{rec.source_key}"
            # AnythingLLM lowercases the title when generating the filename
            prefix = f"raw-{_slugify(title)}".lower()
            if skip_duplicates:
                if url in existing_urls or prefix in existing_prefixes:
                    skipped += 1
                    continue
            try:
                self._push_one(rec, title)
                pushed += 1
                # Track for in-batch dedup (use lowercased prefix to match list query)
                existing_prefixes.add(prefix)
                existing_urls.add(url)
            except Exception as e:
                errors.append(f"{rec.id}: {e}")

        embedded = 0
        if pushed > 0 and self.cfg.auto_embed:
            try:
                self.trigger_embed()
                embedded = pushed
            except Exception as e:
                errors.append(f"trigger_embed: {e}")

        return {"pushed": pushed, "skipped": skipped, "embedded": embedded, "errors": errors}

    def trigger_embed(self) -> dict:
        r = self._session.post(
            f"{self.cfg.base_url}/api/v1/workspace/{self.cfg.workspace_slug}/update-embeddings",
            json={},
            timeout=120,   # embedding can take a while
        )
        r.raise_for_status()
        return r.json()

    # ---- Internals ----

    def _push_one(self, rec: MemoryRecord, title: str) -> dict:
        body = {
            "textContent": _render_for_anythingllm(rec),
            "addToWorkspaces": self.cfg.workspace_slug,
            "metadata": _metadata_for(rec, title),
        }
        r = self._session.post(
            f"{self.cfg.base_url}/api/v1/document/raw-text",
            params={"workspaceSlug": self.cfg.workspace_slug},
            json=body,
            timeout=self.cfg.timeout,
        )
        if not r.ok:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json()


# ---------- Rendering helpers ----------

def _title_for(rec: MemoryRecord) -> str:
    """Deterministic title for an AnythingLLM document."""
    # include source_key for traceability; strip filesystem-unsafe chars
    safe = _slugify(rec.source_key)[:80]
    return f"{rec.source}-{safe}"


def _slugify(s: str) -> str:
    keep = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    return "".join(c if c in keep else "_" for c in s).strip("_") or "unnamed"


def _strip_uuid(filename: str) -> str:
    """Strip trailing -{uuid}.json from AnythingLLM filenames.

    ``raw-openclaw-MEMORY_md-3a8f12bc-9c4d-4f12-8f00-7e9b2e1f23a4.json``
    → ``raw-openclaw-MEMORY_md``
    """
    import re
    name = filename
    if name.endswith(".json"):
        name = name[:-5]
    # Strip -{uuid} suffix (8-4-4-4-12 hex pattern, or any 8+ hex chars)
    name = re.sub(r"-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", "", name)
    name = re.sub(r"-[0-9a-f]{8,}$", "", name)
    return name


def _metadata_for(rec: MemoryRecord, title: str) -> dict:
    """Metadata shape expected by AnythingLLM's metadata-schema endpoint."""
    published = rec.occurred_at or rec.captured_at or int(time.time() * 1000)
    return {
        "title": title,
        "url": f"memory-pipeline://{rec.source}/{rec.source_key}",
        "docAuthor": rec.agent or "memory-pipeline",
        "description": f"{rec.source} / {rec.role} / {rec.project or '-'}",
        "docSource": f"memory-pipeline:{rec.source}",
        "chunkSource": rec.tags[0] if rec.tags else rec.source,
        "published": published,
    }


def _render_for_anythingllm(rec: MemoryRecord) -> str:
    """Render a MemoryRecord as markdown for embedding."""
    parts = [
        f"# {rec.role}",
        "",
        f"- **source**: `{rec.source}`",
        f"- **source_key**: `{rec.source_key}`",
    ]
    if rec.agent:
        parts.append(f"- **agent**: `{rec.agent}`")
    if rec.project:
        parts.append(f"- **project**: `{rec.project}`")
    if rec.occurred_at:
        import datetime as _dt
        parts.append(f"- **occurred_at**: {_dt.datetime.fromtimestamp(rec.occurred_at / 1000).isoformat(timespec='seconds')}")
    if rec.tags:
        parts.append(f"- **tags**: {', '.join(f'`{t}`' for t in rec.tags)}")
    parts += ["", "---", "", rec.content or "_(empty)_", ""]
    return "\n".join(parts)


__all__ = ["AnythingLLMConfig", "AnythingLLMPusher"]