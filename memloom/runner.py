"""Runner: orchestrates one collection pass across all configured agents."""
from __future__ import annotations

from .collectors import AgentAdapter, CollectorContext, get_adapter
from .collectors.base import CollectorContext
from .config import Config
from .pipeline import Deduper, Denoiser, PrivacyFilter, tag_record
from .pipeline.step import PluggablePipeline, REGISTRY as STEP_REGISTRY
from .records import MemoryRecord, RunSummary, Watermark
from .store import RawStore
from .transport import Transport, make_transport


class Runner:
    """Drives the collect → filter → tag → dedup → persist pipeline."""

    def __init__(self, config: Config, store: RawStore | None = None) -> None:
        self.config = config
        self.store = store or RawStore(config.pipeline.data_root)
        self.privacy = PrivacyFilter(
            patterns=config.privacy.strip_patterns,
            replacement=config.privacy.redact_replacement,
        ) if config.privacy.enabled else None
        self.deduper = Deduper()
        self.denoiser = Denoiser() if getattr(config, "denoise", None) and config.denoise.enabled else None

        # Pluggable pipeline (v0.6): build from config.pipeline.steps, fallback to hardcoded chain
        self.pipeline = self._build_pipeline(config)

        # Optional embedder for hybrid search (v0.4). Lazy-init so disabled config
        # doesn't slow down plain FTS5 collects.
        self.embedder = None
        self._embed_text = None
        if getattr(config, "embed", None) and config.embed.enabled:
            try:
                from .embed import EmbedConfig, Embedder
                self.embedder = Embedder(EmbedConfig(
                    base_url=config.embed.base_url,
                    api_key=config.embed.api_key,
                    model=config.embed.model,
                    dimension=config.embed.dimension,
                    batch_size=config.embed.batch_size,
                    timeout=config.embed.timeout,
                    max_retries=config.embed.max_retries,
                    enabled=True,
                ))
                # Bind method for use inside the pull loop
                self._embed_text = self.embedder.embed_one
            except Exception as e:
                # Embedder unavailable — log but don't fail the collect
                self.embedder = None

    def _build_pipeline(self, config: Config) -> PluggablePipeline:
        """Build pipeline from config.pipeline.steps, falling back to hardcoded chain."""
        from .pipeline.builtins import (  # noqa: F811 - triggers registration
            ChunkerStep, DedupStep, DenoiseStep, PrivacyStep, TagStep,
        )

        pipeline = PluggablePipeline()

        # Check if config specifies step list
        step_names = getattr(config.pipeline, "steps", None)
        if step_names:
            for name in step_names:
                cls = STEP_REGISTRY.get(name)
                if cls is None:
                    continue
                if name == "privacy" and not config.privacy.enabled:
                    continue
                if name == "denoise" and not (getattr(config, "denoise", None) and config.denoise.enabled):
                    continue
                kwargs = {}
                if name == "chunker":
                    kwargs["target_size"] = getattr(config.pipeline, "chunk_size", 8192)
                if name == "privacy":
                    kwargs["patterns"] = config.privacy.strip_patterns
                    kwargs["replacement"] = config.privacy.redact_replacement
                pipeline.add(cls(**kwargs))
        else:
            # Fallback: hardcoded chain (backward compat)
            if self.privacy is not None:
                pipeline.add(PrivacyStep(
                    patterns=config.privacy.strip_patterns,
                    replacement=config.privacy.redact_replacement,
                ))
            if self.denoiser is not None:
                pipeline.add(DenoiseStep())
            pipeline.add(TagStep())
            # Dedup is handled separately in the loop (needs watermarks)

        return pipeline

    # ---- Public entry points ----

    def collect_once(
        self,
        only_agents: list[str] | None = None,
        only_hosts: list[str] | None = None,
    ) -> list[RunSummary]:
        """One full pass. Returns per-(agent, host) summaries."""
        summaries: list[RunSummary] = []
        watermarks = self.store.load_watermarks()

        for inst in self.config.all_enabled_agents():
            if only_agents and inst.type not in only_agents:
                continue
            if only_hosts and inst.host not in only_hosts:
                continue

            host_cfg = self.config.host(inst.host)
            if host_cfg is None:
                # No host config → assume "local"
                from .config import HostConfig
                host_cfg = HostConfig(name=inst.host, transport="local")

            summary = self._collect_one(inst.type, inst.host, host_cfg, inst.options, watermarks)
            summaries.append(summary)

        # Save watermarks once after the pass.
        self.store.save_watermarks(watermarks)
        return summaries

    # ---- Internals ----

    def _collect_one(
        self,
        agent_type: str,
        host_name: str,
        host_cfg,
        options: dict,
        watermarks: dict[str, Watermark],
    ) -> RunSummary:
        summary = RunSummary(source=agent_type, host=host_name)

        transport: Transport
        try:
            transport = make_transport(host_cfg)
            if hasattr(transport, "open"):
                transport.open()
        except Exception as e:
            summary.errors.append(f"transport init failed: {e}")
            summary.finish()
            self.store.record_run(summary)
            return summary

        try:
            adapter: AgentAdapter = get_adapter(agent_type, options=options)
        except KeyError as e:
            summary.errors.append(str(e))
            summary.finish()
            self.store.record_run(summary)
            return summary

        try:
            adapter.setup(transport)
            sources = adapter.discover(transport)
        except Exception as e:
            summary.errors.append(f"discover failed: {e}")
            summary.finish()
            self.store.record_run(summary)
            return summary

        summary.discovered = len(sources)
        ctx = CollectorContext(
            transport=transport,
            run_id=summary.run_id,
            last_watermarks=watermarks,
        )

        for src in sources:
            # Tag source with host for traceability
            src.host = host_name
            try:
                for record, wm in adapter.pull(src, ctx):
                    # Run through pluggable pipeline (privacy → denoise → tag → chunker)
                    for processed in self.pipeline.run(record):
                        # Skip synthetic markers
                        if processed.role in ("_skip_marker", "_file_summary"):
                            continue

                        # Dedup
                        if not self.deduper.is_new(processed):
                            summary.duplicates += 1
                            continue

                        # Persist
                        try:
                            inserted = self.store.upsert(processed)
                            if inserted:
                                summary.new_records += 1
                            else:
                                summary.duplicates += 1
                        except Exception as e:
                            summary.errors.append(f"upsert {processed.id}: {e}")

                        # Embed
                        if self.embedder is not None and processed.content:
                            try:
                                vec = self._embed_text(processed.content)
                                if vec is not None:
                                    self.store.upsert_vector(processed.id, vec)
                            except Exception as e:
                                summary.errors.append(f"embed {processed.id}: {e}")

                    watermarks[f"{wm.source}::{wm.source_key}"] = wm
            except Exception as e:
                summary.errors.append(f"pull {src.path}: {e}")

        summary.finish()
        self.store.record_run(summary)
        return summary

    # ---- AnythingLLM push ----

    def push_to_anythingllm(
        self,
        source: str | None = None,
        limit: int = 500,
        skip_duplicates: bool = True,
    ) -> dict:
        """Push records from the local store into AnythingLLM.

        Records are ordered newest-first. We dedupe against anything already
        uploaded to the workspace (by checking doc titles).
        """
        if not self.config.anythingllm.enabled:
            return {"error": "AnythingLLM not enabled in config"}

        from .vector import AnythingLLMConfig, AnythingLLMPusher

        records = self._load_records_for_push(source=source, limit=limit)
        if not records:
            return {"pushed": 0, "skipped": 0, "embedded": 0, "errors": [],
                    "info": "no records to push"}

        if self.denoiser is not None:
            records = [self.denoiser.denoise_record(r)[0] for r in records]
            records = [r for r in records if r.content.strip()]

        pusher = AnythingLLMPusher(AnythingLLMConfig(
            base_url=self.config.anythingllm.base_url,
            api_key=self.config.anythingllm.api_key,
            workspace_slug=self.config.anythingllm.workspace_slug,
            auto_embed=self.config.anythingllm.auto_embed,
        ))
        if not pusher.health_check():
            return {"pushed": 0, "skipped": 0, "embedded": 0,
                    "errors": [f"anythingllm not reachable at {self.config.anythingllm.base_url}"]}

        return pusher.push_records(records, skip_duplicates=skip_duplicates)

    def _load_records_for_push(
        self,
        source: str | None = None,
        limit: int = 500,
    ) -> list:
        """Read back records from the store as MemoryRecord objects."""
        import json as _json
        from pathlib import Path
        raw_root = Path(self.store.root) / "raw"
        if not raw_root.exists():
            return []
        records: list = []
        files = list(raw_root.rglob("*.json"))
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files:
            try:
                d = _json.loads(p.read_text(encoding="utf-8"))
                rec = MemoryRecord.from_dict(d)
            except Exception:
                continue
            if source and rec.source != source:
                continue
            if rec.role.startswith("_"):
                continue
            records.append(rec)
            if len(records) >= limit:
                break
        return records


__all__ = ["Runner"]
