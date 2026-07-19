"""Collector CLI — bind to a Hub and push local sources via ingest."""

from __future__ import annotations

import typer

from .config import CollectorConfig
from .run import run_loop, run_once

collector_app = typer.Typer(
    name="collector",
    help="Run a Hub-bound collector (extract local sources → POST /ingest).",
)


@collector_app.command("run")
def run_cmd(
    config: str = typer.Argument(..., help="Path to collector config YAML"),
    once: bool = typer.Option(
        True,
        "--once/--full",
        help="Incremental with watermarks (default) vs full extract",
    ),
    loop: bool = typer.Option(False, "--loop", help="Run forever with interval sleep"),
    interval: int = typer.Option(0, "--interval", help="Loop sleep seconds (default: config.interval)"),
    source: str = typer.Option("", "--source", help="Only this source type"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print records without pushing"),
) -> None:
    """Extract from configured sources and push to the Hub ingest endpoint."""
    cfg = CollectorConfig.from_yaml(config)
    echo = typer.echo

    if loop and dry_run:
        typer.echo("--loop and --dry-run cannot be combined", err=True)
        raise typer.Exit(1)

    if loop:
        sec = interval if interval > 0 else cfg.interval
        run_loop(cfg, interval=sec, source=source, echo=echo)
        return

    run_once(cfg, once=once, source=source, dry_run=dry_run, echo=echo)
