"""Runner: orchestrates one collection pass across all configured agents."""
from __future__ import annotations

from .collectors import AgentAdapter, CollectorContext, get_adapter
from .collectors.base import CollectorContext
from .config import Config
from .pipeline import Deduper, PrivacyFilter, tag_record
from .records import RunSummary, Watermark
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
                    # 1) Privacy filter
                    if self.privacy is not None:
                        record, _ = self.privacy.filter_record(record)

                    # 2) Skip synthetic markers / summaries from main flow
                    if record.role in ("_skip_marker", "_file_summary"):
                        watermarks[f"{wm.source}::{wm.source_key}"] = wm
                        continue

                    # 3) Tag (project/visibility/tags)
                    record = tag_record(record)

                    # 4) Dedup
                    if not self.deduper.is_new(record):
                        summary.duplicates += 1
                        watermarks[f"{wm.source}::{wm.source_key}"] = wm
                        continue

                    # 5) Persist
                    try:
                        inserted = self.store.upsert(record)
                        if inserted:
                            summary.new_records += 1
                        else:
                            summary.duplicates += 1
                    except Exception as e:
                        summary.errors.append(f"upsert {record.id}: {e}")

                    watermarks[f"{wm.source}::{wm.source_key}"] = wm
            except Exception as e:
                summary.errors.append(f"pull {src.path}: {e}")

        summary.finish()
        self.store.record_run(summary)
        return summary


__all__ = ["Runner"]
