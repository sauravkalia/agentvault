#!/usr/bin/env bash
# AgentVault auto-save hook for Claude Code.
#
# Runs incremental sync after a Claude Code session stops.
# Install: agentvault mcp-install (adds to Claude Code hooks)
#
# This hook:
# 1. Detects new sessions since last sync
# 2. Ingests only new data (deduplication handled by ChromaDB)
# 3. Runs in background to avoid blocking Claude Code

set -euo pipefail

# Resolve agentvault from PATH — do not allow environment override
AGENTVAULT_CMD="$(command -v agentvault 2>/dev/null || true)"

if [[ -z "$AGENTVAULT_CMD" ]]; then
  echo "agentvault not found in PATH, skipping auto-save" >&2
  exit 0
fi

# Verify it's actually the agentvault binary
if [[ "$(basename "$AGENTVAULT_CMD")" != "agentvault" ]]; then
  echo "Invalid agentvault path: $AGENTVAULT_CMD" >&2
  exit 1
fi

# Run ingest in background — only new chunks are added (existing are deduped)
"$AGENTVAULT_CMD" ingest --source claude-code &>/dev/null &
