"""CLI entry point (registered as `memloom` via pyproject.toml)."""
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
from .quarantine import (
    DEFAULT_TRIVIAL_RE,
    list_quarantined,
    move_to_quarantine,
    restore_from_quarantine,
)


app = typer.Typer(
    name="memloom",
    help="memloom: weave your agents' memories into one searchable fabric.",
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
        console.print("[yellow]No agents configured. See config/memloom.yaml.example[/yellow]")
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
def embed(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Only embed records from this source."),
    limit: int = typer.Option(0, "--limit", "-n", help="Max records to embed (0 = all)."),
    force: bool = typer.Option(False, "--force", help="Re-embed even if already vectorized."),
    batch_size: int = typer.Option(32, "--batch-size"),
) -> None:
    """Backfill (or refresh) embeddings for existing records.

    Useful for:
      * Vectorizing data ingested before the embedder was configured
      * Switching to a new embedding model (--force)
      * Recovering from an embedder outage
    """
    cfg = _load_config_or_die(config)
    from .embed import EmbedConfig, Embedder
    from .ops import embed_backfill
    emb_cfg = getattr(cfg, "embed", None)
    if emb_cfg is None or not emb_cfg.enabled:
        console.print("[red]embed.enabled=true required in config.[/red]")
        raise typer.Exit(1)

    store = RawStore(cfg.pipeline.data_root)
    embedder = Embedder(EmbedConfig(
        base_url=emb_cfg.base_url, api_key=emb_cfg.api_key,
        model=emb_cfg.model, dimension=emb_cfg.dimension,
        batch_size=emb_cfg.batch_size, timeout=emb_cfg.timeout,
        max_retries=emb_cfg.max_retries, enabled=True,
    ))

    if not embedder.health_check():
        console.print(f"[red]embedder unreachable at {emb_cfg.base_url}[/red]")
        raise typer.Exit(2)

    result = embed_backfill(
        store, embedder, source=source, limit=limit, force=force, batch_size=batch_size,
    )
    console.print(
        f"[cyan]Embedded: {result['embedded']}  skipped: {result['skipped']}  "
        f"errors: {len(result['errors'])}[/cyan]"
    )
    if result["errors"]:
        for e in result["errors"][:5]:
            console.print(f"  [red]{e}[/red]")


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
    console.print(f"[bold]vectors:[/bold] {stats.get('vectors', 0)}")
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
    hybrid: bool = typer.Option(False, "--hybrid", help="FTS5 + vector RRF fusion (requires embeds)"),
) -> None:
    """Full-text search across collected records (--hybrid adds vector ranking)."""
    cfg = _load_config_or_die(config)
    store = RawStore(cfg.pipeline.data_root)

    if hybrid:
        from .embed import EmbedConfig, Embedder, EmbedError
        emb_cfg = getattr(cfg, "embed", None)
        if emb_cfg is None or not emb_cfg.enabled:
            console.print("[red]--hybrid requires embed.enabled=true in config.[/red]")
            raise typer.Exit(1)
        try:
            embedder = Embedder(EmbedConfig(
                base_url=emb_cfg.base_url, api_key=emb_cfg.api_key,
                model=emb_cfg.model, dimension=emb_cfg.dimension,
                batch_size=emb_cfg.batch_size, timeout=emb_cfg.timeout,
                max_retries=emb_cfg.max_retries, enabled=True,
            ))
            qvec = embedder.embed_one(query)
        except EmbedError as e:
            console.print(f"[red]embed failed: {e}[/red]")
            raise typer.Exit(2)
        results = store.hybrid_search(query, qvec, source=source, limit=limit)
        if not results:
            console.print("[yellow]No matches.[/yellow]")
            raise typer.Exit(0)
        t = Table(title=f"Hybrid: {query!r}")
        for col in ["source", "role", "rrf", "n", "snippet"]:
            t.add_column(col)
        for r in results:
            snip = (r.get("snippet") or "")[:120]
            t.add_row(
                r["source"], r["role"],
                f"{r.get('rrf_score', 0):.4f}", str(r.get("n_methods", 0)), snip,
            )
        console.print(t)
        return

    # Pure FTS5 path
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
    md_files = list(Path(cfg.pipeline.data_root).expanduser().rglob(f"{record_id}.md"))
    if not md_files:
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


# ---- quarantine ----

quarantine_app = typer.Typer(help="Move low-value records out of the active store.")
app.add_typer(quarantine_app, name="quarantine")


@quarantine_app.command("list")
def quarantine_list(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
    """List all quarantined records."""
    cfg = _load_config_or_die(config)
    store = RawStore(cfg.pipeline.data_root)
    items = list_quarantined(store)
    if not items:
        console.print("[yellow]No quarantined records.[/yellow]")
        raise typer.Exit(0)
    t = Table(title=f"Quarantined records ({len(items)})")
    for col in ["id", "source", "role", "captured_at", "path"]:
        t.add_column(col)
    import datetime as _dt
    for r in items:
        ts = _dt.datetime.fromtimestamp(r["captured_at"] / 1000).isoformat(timespec="seconds") if r.get("captured_at") else ""
        t.add_row(
            (r.get("id") or "?")[:16],
            r.get("source") or "",
            r.get("role") or "",
            ts,
            r.get("path") or "",
        )
    console.print(t)


@quarantine_app.command("add")
def quarantine_add(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
    record_ids: Optional[list[str]] = typer.Argument(None, help="Specific record IDs to quarantine"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Apply rule to all records in this source"),
    min_len: int = typer.Option(30, "--min-len", help="Quarantine records shorter than this"),
    auto: bool = typer.Option(False, "--auto", help="Apply default rules to all records"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    reason: str = typer.Option("manual", "--reason", "-r", help="Why these are being quarantined"),
) -> None:
    """Move records to quarantine.

    Modes:
      * ``mp quarantine add rec_abc rec_def`` — specific record IDs
      * ``mp quarantine add --source openclaw_session --auto`` — apply default rules
      * ``mp quarantine add --auto`` — apply rules to all sources
    """
    cfg = _load_config_or_die(config)
    store = RawStore(cfg.pipeline.data_root)

    ids_to_quarantine: list[str] = []

    if record_ids:
        ids_to_quarantine = list(record_ids)
    elif auto:
        from .quarantine import find_quarantine_candidates
        candidates = list(find_quarantine_candidates(store, sources=[source] if source else None))
        if not candidates:
            console.print("[green]No records match quarantine rules.[/green]")
            raise typer.Exit(0)
        console.print(f"Found {len(candidates)} candidates. Reasons:")
        from collections import Counter
        reasons = Counter(r for _, r in candidates)
        for reason, count in reasons.most_common():
            console.print(f"  {count:>4}×  {reason}")
        # Show a few examples
        for rec, why in candidates[:5]:
            console.print(f"  e.g. {rec.id[:16]}  [{rec.role}]  {rec.content[:60]!r}")
        if not yes:
            raise typer.Abort()
        ids_to_quarantine = [r.id for r, _ in candidates]
    else:
        console.print("[red]Provide record_ids or use --auto[/red]")
        raise typer.Exit(1)

    if not ids_to_quarantine:
        console.print("[yellow]Nothing to do.[/yellow]")
        raise typer.Exit(0)

    console.print(f"Quarantining {len(ids_to_quarantine)} records...")
    result = move_to_quarantine(store, ids_to_quarantine, reason=reason)
    console.print(f"  [green]moved:[/green]     {len(result.moved)}")
    console.print(f"  [yellow]not_found:[/yellow] {len(result.not_found)}")
    if result.errors:
        console.print(f"  [red]errors:[/red]    {len(result.errors)}")
        for e in result.errors[:5]:
            console.print(f"    {e}")


@quarantine_app.command("restore")
def quarantine_restore(
    config: Optional[str] = typer.Option(None, "--config", "-c"),
    record_ids: Optional[list[str]] = typer.Argument(None, help="Record IDs to restore"),
    all: bool = typer.Option(False, "--all", help="Restore everything in quarantine"),
) -> None:
    """Move records back from quarantine to the active store."""
    cfg = _load_config_or_die(config)
    store = RawStore(cfg.pipeline.data_root)

    if all:
        items = list_quarantined(store)
        ids = [r["id"] for r in items if r.get("id")]
    elif record_ids:
        ids = list(record_ids)
    else:
        console.print("[red]Provide record_ids or --all[/red]")
        raise typer.Exit(1)

    if not ids:
        console.print("[yellow]Nothing to restore.[/yellow]")
        raise typer.Exit(0)
    result = restore_from_quarantine(store, ids)
    console.print(f"  [green]moved:[/green]     {len(result['moved'])}")
    if result["not_found"]:
        console.print(f"  [yellow]not_found:[/yellow] {len(result['not_found'])}")
    if result["errors"]:
        console.print(f"  [red]errors:[/red]    {len(result['errors'])}")
        for e in result["errors"][:5]:
            console.print(f"    {e}")


@app.command()
def init_config(
    path: str = typer.Argument("./config/memloom.yaml", help="Where to write the config."),
) -> None:
    """Write a starter YAML config to <path>."""
    src = Path(__file__).resolve().parent.parent / "config" / "memloom.yaml.example"
    if not src.exists():
        console.print(f"[red]Example config not found at {src}[/red]")
        raise typer.Exit(1)
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    console.print(f"[green]Wrote {target}[/green]")


@app.command()
def serve(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to YAML config."),
    host: str = typer.Option("0.0.0.0", "--host", help="Bind host (0.0.0.0 for LAN, 127.0.0.1 for local-only)"),
    port: int = typer.Option(8789, "--port", "-p", help="HTTP port"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (dev only)"),
) -> None:
    """Run the memloom HTTP ingest server (POST /ingest, GET /health)."""
    import os
    if not os.environ.get("MEMLOOM_INGEST_KEY"):
        from .ingest_server import generate_key
        key = generate_key()
        console.print("[red]MEMLOOM_INGEST_KEY is not set[/red]")
        console.print(f"\n  Generated a fresh key for you:")
        console.print(f"  [cyan]{key}[/cyan]\n")
        console.print("  Set it before starting the server:")
        console.print(f"  [green]export MEMLOOM_INGEST_KEY={key}[/green]\n")
        raise typer.Exit(1)

    cfg = _load_config_or_die(config)
    from .config import find_config
    from .ingest_server import create_app
    import uvicorn
    cfg_path = find_config(config)
    app = create_app(cfg, config_path=cfg_path)
    console.print(f"[green]memloom server starting on http://{host}:{port}[/green]")
    console.print(f"  data_root: {cfg.pipeline.data_root}")
    console.print("  endpoints:")
    console.print("    POST /ingest          (Bearer auth)")
    console.print("    GET  /health          (no auth)")
    console.print("    GET  /stats           (no auth)")
    console.print("    GET  /api/search      (Bearer auth)")
    console.print("    POST /mcp             (Bearer auth)")
    console.print("    GET  /api/admin/*     (Bearer auth — dashboard)")
    console.print("    GET  /                (SPA if dashboard built)")
    uvicorn.run(app, host=host, port=port, reload=reload, log_level="info")


@app.command()
def ingest(
    file: str = typer.Argument(..., help="Path to JSON file with records."),
    url: str = typer.Option("http://127.0.0.1:8765", "--url", help="memloom-ingest server URL"),
    api_key: Optional[str] = typer.Option(None, "--key", help="Bearer token (or set MEMLOOM_INGEST_KEY env)"),
    skip_embed: bool = typer.Option(False, "--skip-embed", help="Don't auto-embed on server side"),
) -> None:
    """Push records from a JSON file to a memloom-ingest server.

    File format: either a list of records, or ``{"records": [...]}``.
    Each record is a dict that will be parsed into a MemoryRecord.
    """
    import json
    import os
    import requests

    key = api_key or os.environ.get("MEMLOOM_INGEST_KEY")
    if not key:
        console.print("[red]Provide --key or set MEMLOOM_INGEST_KEY env var[/red]")
        raise typer.Exit(1)

    with open(file, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict) and "records" in data:
        records = data["records"]
        if data.get("skip_embed"):
            skip_embed = True
    else:
        console.print("[red]File must be a list of records or {records: [...]}[/red]")
        raise typer.Exit(1)

    console.print(f"  pushing {len(records)} records → {url}")
    try:
        r = requests.post(
            f"{url}/ingest",
            headers={"Authorization": f"Bearer {key}"},
            json={"records": records, "skip_embed": skip_embed},
            timeout=300,
        )
        r.raise_for_status()
        result = r.json()
    except requests.RequestException as e:
        console.print(f"[red]push failed: {e}[/red]")
        if e.response is not None:
            console.print(f"  server response: {e.response.text[:300]}")
        raise typer.Exit(2)

    console.print(f"  [green]accepted:[/green] {result.get('accepted', 0)}")
    console.print(f"  [yellow]skipped:[/yellow]  {result.get('skipped', 0)}")
    if result.get("errors"):
        console.print(f"  [red]errors:[/red]    {len(result['errors'])}")
        for e in result["errors"][:5]:
            console.print(f"    {e}")


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


# ── sync subcommand ──────────────────────────────────────────────────────────
from .sync.cli import sync_app

app.add_typer(sync_app)

if __name__ == "__main__":
    app()