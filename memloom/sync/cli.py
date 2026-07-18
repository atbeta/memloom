"""Sync CLI — push local agent stores to a memloom ingest server."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests
import typer

from memloom.sync.adapter import SyncAdapter, WatermarkStore
from memloom.sync.antigravity import AntigravityAdapter
from memloom.sync.codex import CodexAdapter
from memloom.sync.config import SyncConfig
from memloom.sync.kilocode import KiloCodeAdapter
from memloom.sync.opencode import OpenCodeAdapter
from memloom.sync.openclaw_session import OpenClawSessionAdapter
from memloom.sync.qoder import QoderAdapter

sync_app = typer.Typer(name="sync", help="Push local agent stores to memloom ingest server.")

ADAPTER_REGISTRY: dict[str, type[SyncAdapter]] = {
    "opencode": OpenCodeAdapter,
    "codex": CodexAdapter,
    "antigravity": AntigravityAdapter,
    "openclaw_session": OpenClawSessionAdapter,
    "qoder": QoderAdapter,
    "kilocode": KiloCodeAdapter,
}


def _batched_post(endpoint: str, api_key: str, records: list[dict], batch_size: int, skip_embed: bool) -> dict:
    """POST records to /ingest in batches, return summary."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    total_accepted = 0
    total_errors = 0
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
        typer.echo(
            f"  batch {i // batch_size + 1}: accepted={result.get('accepted')}, "
            f"skipped={result.get('skipped')}, errors={len(result.get('errors', []))}"
        )
    return {"accepted": total_accepted, "errors": total_errors}


@sync_app.command()
def run(
    config: str = typer.Argument(..., help="Path to sync config YAML"),
    once: bool = typer.Option(False, "--once", help="Run once (incremental, uses watermarks)"),
    source: str = typer.Option("", "--source", help="Only sync this source"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print records without pushing"),
):
    """Run one sync pass from local agent stores to memloom ingest server."""
    cfg = SyncConfig.from_yaml(config)
    store = WatermarkStore(cfg.state_dir)
    watermarks = store.load() if once else {}
    total = 0

    for src_cfg in cfg.sources:
        if source and src_cfg.type != source:
            continue

        adapter_cls = ADAPTER_REGISTRY.get(src_cfg.type)
        if not adapter_cls:
            typer.echo(f"[{src_cfg.type}] unknown adapter type, skipping", err=True)
            continue

        path = src_cfg.db or src_cfg.session_dir
        if not path:
            typer.echo(f"[{src_cfg.type}] no db/session_dir configured, skipping", err=True)
            continue

        typer.echo(f"[{src_cfg.type}] extracting from {path} ...")
        adapter = adapter_cls(path)

        since = watermarks.get(src_cfg.type) if once else None
        try:
            records = adapter.extract(since)
        except Exception as e:
            typer.echo(f"[{src_cfg.type}] error: {e}", err=True)
            import traceback
            traceback.print_exc()
            continue

        typer.echo(f"[{src_cfg.type}] found {len(records)} records (since={since})")

        if not records:
            # Still update watermark even if no new records
            watermarks[src_cfg.type] = adapter.get_latest_cursor()
            store.save(watermarks)
            continue

        if dry_run:
            _print_records(records)
            typer.echo(f"[{src_cfg.type}] dry-run: would push {len(records)} records")
        else:
            payload = [r.to_dict() for r in records]
            summary = _batched_post(cfg.endpoint, cfg.api_key, payload, cfg.batch_size, cfg.skip_embed)
            typer.echo(
                f"[{src_cfg.type}] pushed: accepted={summary['accepted']}, errors={summary['errors']}"
            )
            total += summary["accepted"]

        watermarks[src_cfg.type] = adapter.get_latest_cursor()
        store.save(watermarks)

    if not dry_run:
        typer.echo(f"\nTotal accepted: {total}")


def _print_records(records: list) -> None:
    for r in records[:5]:
        typer.echo(
            f"  [{r.source}] {r.source_key[:40]} | {r.agent[:30]} | "
            f"{len(r.content)} chars | {r.project or '-'}"
        )
    if len(records) > 5:
        typer.echo(f"  ... and {len(records) - 5} more")
