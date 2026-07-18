"""CLI entry point (registered as `mp` via pyproject.toml)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import find_config, load_config
from .runner import Runner
from .store import RawStore


app = typer.Typer(
    name="mp",
    help="memory-pipeline: unified agent memory collection.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


def _load_config_or_die(path: Optional[str]) -> object:
    cfg = load_config(path)
    if not cfg.hosts:
        from .config import HostConfig
        cfg.hosts = [HostConfig(name="local", transport="local")]
    if not cfg.agents:
        console.print("[yellow]No agents configured. See config/memory-pipeline.yaml.example[/yellow]")
    return cfg


@app.command()
def collect(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to YAML config."),
    agents: Optional[str] = typer.Option(None, "--agents", "-a", help="Comma-separated agent types to run."),
    hosts: Optional[str] = typer.Option(None, "--hosts", help="Comma-separated host names to run."),
    push: bool = typer.Option(False, "--push", help="Push to AnythingLLM after collection."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run one collection pass."""
    cfg = _load_config_or_die(config)
    runner = Runner(cfg)
    only_agents = [x.strip() for x in agents.split(",")] if agents else None
    only_hosts = [x.strip() for x in hosts.split(",")] if hosts else None
    summaries = runner.collect_once(only_agents=only_agents, only_hosts=only_hosts)

    table = Table(title="Collection summary")
    for col in ["source", "host", "discovered", "new", "dup", "filtered", "errors", "ms"]:
        table.add_column(col)
    for s in summaries:
        table.add_row(
            s.source, s.host, str(s.discovered), str(s.new_records),
            str(s.duplicates), str(s.filtered),
            str(len(s.errors)), str(s.duration_ms),
        )
    console.print(table)

    if push:
        pushed = runner.push_to_anythingllm()
        console.print(f"[cyan]AnythingLLM push:[/cyan] {pushed}")


@app.command()
def status(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Show collection stats and recent runs."""
    cfg = _load_config_or_die(config)
    store = RawStore(cfg.pipeline.data_root)
    stats = store.stats()
    console.print(f"[bold]data_root:[/bold] {cfg.pipeline.data_root}")
    console.print(f"[bold]total records:[/bold] {stats['total']}")
    if stats["by_source"]:
        t = Table(title="By source")
        t.add_column("source")
        t.add_column("count", justify="right")
        for s, n in stats["by_source"].items():
            t.add_row(s, str(n))
        console.print(t)

    runs = store.recent_runs(limit=10)
    if runs:
        t = Table(title="Recent runs")
        for col in ["started_at", "source", "host", "new", "dup", "filtered", "errors"]:
            t.add_column(col)
        import datetime as _dt
        for r in runs:
            started = r["started_at"]
            ts = _dt.datetime.fromtimestamp(started / 1000).isoformat(timespec="seconds") if started else ""
            t.add_row(
                ts, r["source"] or "", r["host"] or "",
                str(r["new_records"]), str(r["duplicates"]), str(r["filtered"]),
                str(len(r["errors"])),
            )
        console.print(t)


@app.command()
def search(
    query: str = typer.Argument(..., help="FTS5 query string."),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
    source: Optional[str] = typer.Option(None, "--source", "-s"),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """Full-text search across collected records."""
    cfg = _load_config_or_die(config)
    store = RawStore(cfg.pipeline.data_root)
    results = store.search(query, source=source, limit=limit)
    if not results:
        console.print("[yellow]No matches.[/yellow]")
        raise typer.Exit(0)
    t = Table(title=f"Search: {query!r}")
    for col in ["source", "role", "project", "captured_at", "snippet"]:
        t.add_column(col)
    for r in results:
        ts = _fmt_ts(r["captured_at"])
        snip = (r["snippet"] or "")[:120]
        t.add_row(r["source"], r["role"], r["project"] or "", ts, snip)
    console.print(t)


@app.command()
def inspect(
    record_id: str = typer.Argument(..., help="Record id (rec_...)"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """Print full content of a record by id."""
    cfg = _load_config_or_die(config)
    RawStore(cfg.pipeline.data_root)
    # We don't expose get-by-id directly; use the markdown mirror under raw/
    # Walk the raw dir looking for the matching md file. Cheap for v0.1.
    md_files = list(Path(cfg.pipeline.data_root).expanduser().rglob(f"{record_id}.md"))
    if not md_files:
        # try by rec_ prefix
        md_files = list(Path(cfg.pipeline.data_root).expanduser().rglob(f"*{record_id}*.md"))
    if not md_files:
        console.print(f"[red]Not found: {record_id}[/red]")
        raise typer.Exit(1)
    console.print(md_files[0].read_text(encoding="utf-8"))


@app.command()
def push(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Only push records from this source."),
    limit: int = typer.Option(500, "--limit", "-n", help="Max records to push (newest first)."),
    no_dedup: bool = typer.Option(False, "--no-dedup", help="Push even if already in AnythingLLM."),
) -> None:
    """Push collected records into AnythingLLM for semantic search."""
    cfg = _load_config_or_die(config)
    if not cfg.anythingllm.enabled:
        console.print("[red]AnythingLLM not enabled in config.[/red]")
        raise typer.Exit(1)

    runner = Runner(cfg)
    result = runner.push_to_anythingllm(source=source, limit=limit, skip_duplicates=not no_dedup)
    console.print(f"[cyan]AnythingLLM push:[/cyan] {result}")


@app.command()
def init_config(
    path: str = typer.Argument("./config/memory-pipeline.yaml", help="Where to write the config."),
) -> None:
    """Write a starter YAML config to <path>."""
    src = Path(__file__).resolve().parent.parent / "config" / "memory-pipeline.yaml.example"
    if not src.exists():
        console.print(f"[red]Example config not found at {src}[/red]")
        raise typer.Exit(1)
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    console.print(f"[green]Wrote {target}[/green]")


@app.command()
def agents() -> None:
    """List built-in agent adapters."""
    from .collectors import known_agents
    console.print("Built-in adapters:")
    for a in known_agents():
        console.print(f"  - {a}")


def _fmt_ts(ms: int) -> str:
    import datetime as _dt
    if not ms:
        return ""
    return _dt.datetime.fromtimestamp(ms / 1000).isoformat(timespec="seconds")


if __name__ == "__main__":
    app()