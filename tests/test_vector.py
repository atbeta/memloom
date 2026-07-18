"""Tests for the AnythingLLM pusher.

Uses an in-process fake to verify request shapes without needing a real
AnythingLLM. End-to-end with a real AnythingLLM is verified manually.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from memloom.records import MemoryRecord
from memloom.vector import AnythingLLMConfig, AnythingLLMPusher


@dataclass
class FakeResponse:
    status_code: int = 200
    _content: bytes = b"{}"

    def json(self):
        return json.loads(self._content or b"{}")

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


@dataclass
class FakeSession:
    calls: list[dict] = field(default_factory=list)
    docs: list[dict] = field(default_factory=list)

    def _make_response(self, url: str, body: dict) -> FakeResponse:
        if url.endswith("/api/ping"):
            return FakeResponse(_content=json.dumps({"online": True}).encode())
        if url.endswith("/update-embeddings"):
            return FakeResponse(_content=json.dumps({"workspace": {"documents": self.docs}}).encode())
        if url.endswith("/api/v1/workspace/ai-knowledge") and "workspace/ai-knowledge" in url:
            return FakeResponse(_content=json.dumps({
                "workspace": [{"id": 1, "slug": "ai-knowledge", "documents": self.docs}]
            }).encode())
        if url.endswith("/api/v1/document/raw-text"):
            title = body.get("metadata", {}).get("title", "fake")
            import uuid as _uuid
            slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)
            fn = f"raw-{slug}-{_uuid.uuid4().hex[:8]}.json"
            doc = {
                "id": "fake-id", "filename": fn,
                "title": title, "wordCount": 10, "token_count_estimate": 20,
                "metadata": json.dumps(body.get("metadata", {})),
            }
            self.docs.append(doc)
            return FakeResponse(_content=json.dumps({"success": True, "documents": [doc]}).encode())
        return FakeResponse(_content=b"{}")

    def get(self, url, timeout=None, **kwargs):
        self.calls.append({"method": "GET", "url": url, "kwargs": kwargs})
        return self._make_response(url, {})

    def post(self, url, json=None, params=None, timeout=None, **kwargs):
        self.calls.append({"method": "POST", "url": url, "body": json, "params": params})
        return self._make_response(url, json or {})


def _record(source: str = "openclaw", key: str = "MEMORY.md") -> MemoryRecord:
    return MemoryRecord(
        source=source,
        source_key=f"/some/path/{key}",
        role="long_term_memory",
        content="hello world",
        project="workspace",
    )


def _make_pusher_with_fake():
    pusher = AnythingLLMPusher(AnythingLLMConfig(
        base_url="http://fake:3001",
        api_key="test-key",
        workspace_slug="ai-knowledge",
    ))
    fake = FakeSession()
    pusher._session = fake
    return pusher, fake


def test_health_check():
    pusher, _ = _make_pusher_with_fake()
    assert pusher.health_check() is True


def test_push_records_calls_raw_text_endpoint():
    pusher, fake = _make_pusher_with_fake()
    result = pusher.push_records([_record()])
    assert result["pushed"] == 1
    assert result["errors"] == []
    raw_calls = [c for c in fake.calls if "raw-text" in c["url"]]
    assert len(raw_calls) == 1
    body = raw_calls[0]["body"]
    assert body["addToWorkspaces"] == "ai-knowledge"
    assert "hello world" in body["textContent"]
    assert body["metadata"]["title"]


def test_push_records_skips_duplicates():
    pusher, _ = _make_pusher_with_fake()
    pusher.push_records([_record(source="openclaw", key="MEMORY.md")])
    # Second push of same source_key should skip
    result = pusher.push_records([_record(source="openclaw", key="MEMORY.md")])
    assert result["skipped"] == 1
    assert result["pushed"] == 0


def test_push_records_no_dedup_pushes_again():
    pusher, _ = _make_pusher_with_fake()
    pusher.push_records([_record()])
    result = pusher.push_records([_record()], skip_duplicates=False)
    assert result["pushed"] == 1


def test_metadata_shape_matches_schema():
    pusher, fake = _make_pusher_with_fake()
    rec = _record()
    pusher.push_records([rec])
    raw_call = next(c for c in fake.calls if "raw-text" in c["url"])
    md = raw_call["body"]["metadata"]
    # AnythingLLM metadata-schema requires these keys
    for required in ("title", "url", "docAuthor", "description", "docSource", "chunkSource", "published"):
        assert required in md, f"missing {required} in metadata"


def test_auto_embed_triggered_once_per_batch():
    pusher, fake = _make_pusher_with_fake()
    pusher.push_records([_record(key="a.md"), _record(key="b.md")])
    embed_calls = [c for c in fake.calls if "update-embeddings" in c["url"]]
    assert len(embed_calls) == 1  # batched, not per-record


def test_auto_embed_disabled_skips_embed():
    pusher, fake = _make_pusher_with_fake()
    pusher.cfg.auto_embed = False
    pusher.push_records([_record()])
    embed_calls = [c for c in fake.calls if "update-embeddings" in c["url"]]
    assert len(embed_calls) == 0