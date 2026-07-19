"""One collector pass: extract → POST /ingest."""

from __future__ import annotations

import time
from typing import Callable

import requests

from memloom.sync.adapter import WatermarkStore

from .config import CollectorConfig
from .registry import ADAPTER_REGISTRY, build_adapter


def batched_post(
    endpoint: str,
    api_key: str,
    records: list[dict],
    batch_size: int,
    skip_embed: bool,
    echo: Callable[[str], None] | None = None,
) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    total_accepted = 0
    total_errors = 0
    _echo = echo or (lambda _s: None)
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        resp = requests.post(
            endpoint,
            headers=headers,
            json={"records": batch, "skip_embed": skip_embed},
            timeout=300,
        )
        resp.raise_for_status()
        result = resp.json()
        total_accepted += result.get("accepted", 0)
        total_errors += len(result.get("errors", []))
        _echo(
            f"  batch {i // batch_size + 1}: accepted={result.get('accepted')}, "
            f"skipped={result.get('skipped')}, errors={len(result.get('errors', []))}"
        )
    return {"accepted": total_accepted, "errors": total_errors}


def run_once(
    cfg: CollectorConfig,
    *,
    once: bool = True,
    source: str = "",
    dry_run: bool = False,
    echo: Callable[[str], None] | None = None,
) -> int:
    """Run one pass. Returns total accepted (0 on dry-run)."""
    _echo = echo or (lambda _s: None)
    store = WatermarkStore(cfg.state_dir)
    watermarks = store.load() if once else {}
    total = 0

    if not dry_run and not cfg.api_key:
        raise RuntimeError("api_key missing — set in YAML or MEMLOOM_INGEST_KEY")

    for src_cfg in cfg.sources:
        if source and src_cfg.type != source:
            continue

        if src_cfg.type not in ADAPTER_REGISTRY:
            _echo(f"[{src_cfg.type}] unknown adapter type, skipping")
            continue

        adapter = build_adapter(src_cfg)
        if adapter is None:
            _echo(f"[{src_cfg.type}] no path/uri configured, skipping")
            continue

        path = getattr(adapter, "source_path", "") or src_cfg.type
        _echo(f"[{src_cfg.type}] extracting from {path} ...")

        since = watermarks.get(src_cfg.type) if once else None
        try:
            records = adapter.extract(since)
        except Exception as e:
            _echo(f"[{src_cfg.type}] error: {e}")
            import traceback

            traceback.print_exc()
            continue

        _echo(f"[{src_cfg.type}] found {len(records)} records (since={since})")

        if not records:
            watermarks[src_cfg.type] = adapter.get_latest_cursor()
            store.save(watermarks)
            continue

        if dry_run:
            for r in records[:5]:
                _echo(
                    f"  [{r.source}] {r.source_key[:40]} | {r.agent[:30]} | "
                    f"{len(r.content)} chars | {r.project or '-'}"
                )
            if len(records) > 5:
                _echo(f"  ... and {len(records) - 5} more")
            _echo(f"[{src_cfg.type}] dry-run: would push {len(records)} records")
        else:
            payload = [r.to_dict() for r in records]
            summary = batched_post(
                cfg.endpoint, cfg.api_key, payload, cfg.batch_size, cfg.skip_embed, echo=_echo
            )
            _echo(
                f"[{src_cfg.type}] pushed: accepted={summary['accepted']}, errors={summary['errors']}"
            )
            total += summary["accepted"]

        watermarks[src_cfg.type] = adapter.get_latest_cursor()
        store.save(watermarks)

    if not dry_run:
        _echo(f"\nTotal accepted: {total}")
    return total


def run_loop(
    cfg: CollectorConfig,
    *,
    interval: int | None = None,
    source: str = "",
    echo: Callable[[str], None] | None = None,
) -> None:
    """Run forever with sleep between passes."""
    _echo = echo or (lambda _s: None)
    sec = interval if interval is not None else cfg.interval
    while True:
        _echo(f"--- collector pass (interval={sec}s) ---")
        try:
            run_once(cfg, once=True, source=source, dry_run=False, echo=_echo)
        except Exception as e:
            _echo(f"collector pass failed: {e}")
        time.sleep(sec)
