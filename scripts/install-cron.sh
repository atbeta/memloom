#!/usr/bin/env bash
# Register `mp collect` to run every 5 minutes via cron.
# Idempotent — re-running updates the existing entry.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$(command -v uv && uv run --directory "$PROJECT_ROOT" which python || command -v python3)}"
CRON_LINE="*/5 * * * * cd $PROJECT_ROOT && $PYTHON_BIN -m memory_pipeline.cli collect --config $PROJECT_ROOT/config/memory-pipeline.yaml >> $PROJECT_ROOT/data/cron.log 2>&1"

# Strip existing entries for this project
( crontab -l 2>/dev/null | grep -v "memory-pipeline.yaml" || true ) > /tmp/cron.tmp
echo "$CRON_LINE" >> /tmp/cron.tmp
crontab /tmp/cron.tmp
rm /tmp/cron.tmp

echo "Installed cron:"
echo "  $CRON_LINE"
crontab -l | grep memory-pipeline || true