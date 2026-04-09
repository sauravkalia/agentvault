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

AGENTVAULT_CMD="${AGENTVAULT_CMD:-agentvault}"

# Run ingest in background — only new chunks are added (existing are deduped)
"$AGENTVAULT_CMD" ingest --source claude-code &>/dev/null &
