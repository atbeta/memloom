"""OpenClaw session trajectory sync adapter — reads *.trajectory.jsonl files.

Source: OpenClaw ~/.openclaw/agents/main/sessions/*.trajectory.jsonl
Each file contains OTEL events grouped by runId into conversation turns.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from memloom.sync.adapter import SyncAdapter


class OpenClawSessionAdapter(SyncAdapter):
    source_type = "openclaw_session"

    def extract(self, since_ms: int | None = None) -> list:
        from memloom.records import MemoryRecord

        records: list[MemoryRecord] = []
        sessions_dir = Path(self.source_path).expanduser()
        if not sessions_dir.is_dir():
            return records

        for jsonl_file in sorted(sessions_dir.glob("*.trajectory.jsonl")):
            if ".deleted." in jsonl_file.name:
                continue
            mtime_ms = int(jsonl_file.stat().st_mtime * 1000)
            if since_ms and mtime_ms < since_ms:
                continue

            try:
                raw = jsonl_file.read_text(encoding="utf-8")
            except OSError:
                continue

            session_id = jsonl_file.stem.replace(".trajectory", "")
            workspace_dir = ""

            # Bucket events by runId
            runs: dict[str, dict] = defaultdict(dict)
            session_meta: dict = {}
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                et = ev.get("type", "")
                rid = ev.get("runId") or ev.get("traceId") or "_"
                if not workspace_dir:
                    workspace_dir = ev.get("workspaceDir") or ""
                if et in ("prompt.submitted", "model.completed", "trace.artifacts"):
                    runs[rid][et] = ev
                elif et == "session.started":
                    session_meta = ev.get("data", {}) or {}
                elif et == "trace.metadata":
                    runs[rid]["__metadata__"] = ev

            for rid in sorted(runs.keys()):
                if rid == "_" or rid == "__metadata__":
                    continue
                payload = runs[rid]
                prompt_ev = payload.get("prompt.submitted")
                response_ev = payload.get("model.completed")
                if not prompt_ev and not response_ev:
                    continue

                prompt_text = ""
                if prompt_ev:
                    prompt_text = (prompt_ev.get("data") or {}).get("prompt") or ""
                response_text = ""
                if response_ev:
                    data = response_ev.get("data") or {}
                    texts = data.get("assistantTexts") or []
                    response_text = "\n".join(t for t in texts if t)

                if not prompt_text and not response_text:
                    continue

                ts = _parse_ts((prompt_ev or response_ev).get("ts"))
                model_id = (prompt_ev or response_ev).get("modelId") or ""

                parts = []
                if prompt_text:
                    parts.append(f"**USER**: {prompt_text}")
                if response_text:
                    short_model = (model_id or "?").split("/")[-1]
                    parts.append(f"**ASSISTANT** ({short_model}): {response_text}")
                content = "\n\n".join(parts)

                records.append(MemoryRecord(
                    source=self.source_type,
                    source_key=f"{session_id}#{rid}",
                    content=content,
                    role="conversation_turn",
                    agent=f"openclaw:{model_id}" if model_id else "openclaw",
                    project=Path(workspace_dir).name if workspace_dir else None,
                    occurred_at=ts,
                    raw_meta={
                        "session_id": session_id,
                        "run_id": rid,
                        "workspace_dir": workspace_dir,
                        "model_id": model_id,
                        "provider": (prompt_ev or response_ev or {}).get("provider", ""),
                        "session_meta": session_meta,
                    },
                ))

        return records

    def get_latest_cursor(self) -> int:
        sessions_dir = Path(self.source_path).expanduser()
        if not sessions_dir.is_dir():
            return 0
        latest = 0
        for f in sessions_dir.glob("*.trajectory.jsonl"):
            if ".deleted." not in f.name:
                latest = max(latest, int(f.stat().st_mtime * 1000))
        return latest


def _parse_ts(s) -> int | None:
    if not s:
        return None
    try:
        import datetime as _dt
        return int(_dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except (ValueError, TypeError):
        return None
