# AgentVault

Unified memory layer that consolidates history from all your AI coding agents — searchable by humans (Obsidian) and by AI (MCP).

Every conversation you have across Claude Code, OpenCode, Codex, Cursor — all siloed. Start a new session and your agent has zero context from any of them. AgentVault fixes that.

## How It Works

```
Terminal 1: Claude Code (project A)  ─┐
Terminal 2: Claude Code (project B)  ─┤
Terminal 3: OpenCode                 ─┼──→ AgentVault ──→ ChromaDB (AI search)
Terminal 4: Codex                    ─┤                └──→ Obsidian (you browse)
IDE: Cursor                          ─┘

New session starts → MCP tools → semantic search → relevant context returned
```

- **No context window bloat** — loads ~250 tokens on startup, searches on demand (~500-2000 tokens per query)
- **Fast** — local ChromaDB with HNSW index, ~30-50ms per search
- **Private** — everything stays on your machine, zero API calls, zero cloud
- **Obsidian-native** — browsable markdown files with frontmatter, daily digests, per-project folders

## Quick Start

```bash
# Install
pip install agentvault-memory

# Initialize — auto-detects your AI tools
agentvault init --obsidian ~/path/to/your/obsidian/vault

# Ingest all history
agentvault ingest

# Search anything
agentvault search "why did we switch to GraphQL"
agentvault search "auth bug" --project sphere-web
agentvault search "rate limiting" --source claude-code

# Check status
agentvault status

# Connect to Claude Code (so new sessions can query your vault)
agentvault mcp-install
```

Restart Claude Code after `mcp-install`. Your AI now has access to your entire history.

## What Gets Indexed

From each session, AgentVault extracts:

| Field | Source |
|-------|--------|
| **Conversations** | User messages + AI responses |
| **Project** | Working directory |
| **Git branch** | Active branch during session |
| **Files touched** | Files read/edited/written by the AI |
| **Timestamps** | Session start/end, per-message |
| **Tool usage** | Which tools the AI called |

## MCP Tools

When connected via `agentvault mcp-install`, your AI gets these tools:

| Tool | What It Does |
|------|-------------|
| `vault_search` | Semantic search with project/source/branch filters |
| `vault_project_context` | "What have I done on project X recently?" |
| `vault_cross_reference` | "Did I solve this problem before in another project?" |
| `vault_status` | Overview of indexed sessions and projects |

Your AI calls these automatically when you ask questions like:
- *"Remember that auth bug we fixed last week?"*
- *"How did we handle rate limiting in the other project?"*
- *"What decisions did I make about the database?"*

## Obsidian Integration

AgentVault writes browsable markdown to your Obsidian vault:

```
obsidian-vault/
  agent-history/
    2026-04-09.md                      ← daily digest
    sphere-web/
      2026-04-09-4f66f16f.md           ← session transcript
    evaluate-explorer/
      2026-04-08-aa20d038.md
```

Each session file has YAML frontmatter (source, project, date, branch, tags) — searchable and linkable in Obsidian.

## Supported Tools

| Tool | Status | History Location |
|------|--------|-----------------|
| **Claude Code** | **Supported** | `~/.claude/projects/` |
| OpenCode | Planned | `~/.opencode/` |
| Codex | Planned | TBD |
| Cursor | Planned | TBD |
| ChatGPT | Planned (manual export) | TBD |

## Adding a New Adapter

Each adapter is one file implementing 3 methods:

```python
from agentvault.adapters.base import BaseAdapter

class MyToolAdapter(BaseAdapter):
    name = "my-tool"
    description = "My AI tool"

    def default_history_path(self) -> Path:
        return Path.home() / ".my-tool" / "history"

    def detect(self) -> bool:
        return self.history_path.exists()

    def discover_sessions(self) -> list[Path]:
        return list(self.history_path.glob("*.json"))

    def parse_session(self, path: Path) -> AgentSession | None:
        # Convert native format → AgentSession schema
        ...
```

See `agentvault/adapters/claude_code.py` for a full example.

## Architecture

```
agentvault/
  cli.py                  ← CLI (click + rich)
  config.py               ← ~/.agentvault/config.json
  mcp_server.py           ← MCP server (stdio transport)
  core/
    schema.py             ← AgentSession, Exchange, Chunk
    store.py              ← ChromaDB wrapper
    ingester.py           ← Session → chunks
  adapters/
    base.py               ← BaseAdapter interface
    claude_code.py        ← Claude Code JSONL parser
  writers/
    obsidian.py           ← Markdown + daily digests
    chromadb_writer.py    ← Batch ingestion + dedup
  hooks/
    auto_save.sh          ← Post-session sync hook
```

## Context Efficiency

AgentVault does NOT load all history into context. It uses a layered approach:

| Layer | When | Tokens |
|-------|------|--------|
| L0+L1 (identity + active context) | Session start | ~250 |
| L2 (on-demand search) | When asked | ~500-2000 per query |

10 searches in a session = ~15K tokens. That's 91% of a 200K context window left free for actual work.

## Requirements

- Python 3.9+
- No API keys
- No Docker
- No internet after install (embedding model downloaded once, ~80MB)

## Inspiration

Inspired by [MemPalace](https://github.com/milla-jovovich/mempalace) — which proved that raw ChromaDB retrieval achieves 96.6% recall on LongMemEval with zero API calls. AgentVault applies this to the specific problem of multi-agent session consolidation for developers.

## License

MIT
