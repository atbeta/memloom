"""Sync CLI — deprecated alias for ``memloom collector``."""

from __future__ import annotations

import typer

from memloom.collector.config import CollectorConfig
from memloom.collector.run import run_once

sync_app = typer.Typer(
    name="sync",
    help="[deprecated] Use `memloom collector` — push local stores to Hub ingest.",
)


@sync_app.command()
def run(
    config: str = typer.Argument(..., help="Path to sync/collector config YAML"),
    once: bool = typer.Option(False, "--once", help="Run once (incremental, uses watermarks)"),
    source: str = typer.Option("", "--source", help="Only sync this source"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print records without pushing"),
):
    """Deprecated: prefer `memloom collector run`."""
    typer.echo(
        "warning: `memloom sync` is deprecated; use `memloom collector run`",
        err=True,
    )
    cfg = CollectorConfig.from_yaml(config)
    # Legacy: without --once = full extract; with --once = incremental
    run_once(cfg, once=once, source=source, dry_run=dry_run, echo=typer.echo)
