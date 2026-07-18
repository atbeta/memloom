"""Antigravity brain sync adapter — reads ~/.gemini/antigravity/brain/ markdown."""

from __future__ import annotations

import json
import os
from pathlib import Path

from memloom.sync.adapter import SyncAdapter


class AntigravityAdapter(SyncAdapter):
    source_type = "antigravity"

    def extract(self, since_ms: int | None = None) -> list:
        from memloom.records import MemoryRecord

        records: list[MemoryRecord] = []
        if not os.path.isdir(self.source_path):
            return records

        brain_dir = Path(self.source_path)
        since_s = int(since_ms / 1000) if since_ms else 0

        for region in sorted(brain_dir.iterdir()):
            if not region.is_dir():
                continue
            region_name = region.name

            for md_file in sorted(region.glob("*.md")):
                mtime_ms = int(md_file.stat().st_mtime * 1000)
                if since_ms and mtime_ms < since_ms:
                    continue

                content = md_file.read_text(encoding="utf-8").strip()
                if not content:
                    continue

                stub = md_file.stem.replace("_", " ").title()
                source_key = f"{region_name}/{md_file.name}"

                records.append(MemoryRecord(
                    source=self.source_type,
                    source_key=source_key,
                    content=content,
                    role="note",
                    occurred_at=mtime_ms,
                    raw_meta={
                        "title": stub,
                        "region": region_name,
                        "filename": md_file.name,
                    },
                ))

        return records

    def get_latest_cursor(self) -> int:
        if not os.path.isdir(self.source_path):
            return 0
        latest = 0
        for region in Path(self.source_path).iterdir():
            if not region.is_dir():
                continue
            for md_file in region.glob("*.md"):
                mtime = int(md_file.stat().st_mtime * 1000)
                latest = max(latest, mtime)
        return latest
