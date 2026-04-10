# AgentVault

Unified memory layer that consolidates history from all your AI coding agents — searchable by humans (Obsidian) and by AI (MCP).

Every conversation you have across Claude Code, OpenCode, Codex, Cursor — all siloed. Start a new session and your agent has zero context from any of them. AgentVault fixes that.

## The Problem

Developers now use 3-4 AI coding tools daily — Claude Code in one terminal, Cursor in the IDE, Codex for quick tasks, OpenCode for another project. Every decision, every debugging session, every architecture discussion happens in these conversations. Then the session ends and it's gone.

**6 months of daily AI use = ~19.5 million tokens of conversations.** That's every decision, every "we tried X and it failed because Y", every debugging session. All trapped in separate tools that don't talk to each other.

You open a new Claude Code session and ask *"how did we handle auth?"* — it has no idea. The answer is in a Cursor session from last month. Or a Codex session from last week. Or three different Claude Code sessions across two projects.

## Why AgentVault

There are many AI memory tools — MemPalace, Mem0, Zep, Letta, Pieces. None of them solve this specific problem.

| | AgentVault | MemPalace | Mem0 | Zep | Pieces | Claude Auto Dream |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| **Reads history from Claude Code** | Yes | No | No | No | No | Yes |
| **Reads history from Cursor** | Yes | No | No | No | No | No |
| **Reads history from Codex** | Yes | No | No | No | No | No |
| **Reads history from OpenCode** | Yes | No | No | No | No | No |
| **Cross-tool semantic search** | Yes | — | — | — | — | No |
| **Obsidian output** | Yes | No | No | No | No | No |
| **MCP server for AI querying** | Yes | Yes | No | No | No | — |
| **Zero API keys** | Yes | Yes | No | No | No | Yes |
| **Fully local** | Yes | Yes | No | No | No | Yes |
| **Free** | Yes | Yes | Free tier | $25/mo+ | $10/mo | Yes |

**The core difference:** Other tools store what the AI *decides* to remember. AgentVault reads the raw conversation history files that your tools already store on disk — every word, every decision, every debugging session — and makes it all searchable. Nothing is lost because nothing is summarized away.

## Token Efficiency

The obvious question: if you have 19.5M tokens of history, how do you use it without blowing up the context window?

**You don't load it.** AgentVault uses vector search — it only retrieves what's relevant to your question.

| Approach | Tokens loaded | Annual cost | What you lose |
|----------|:---:|:---:|---|
| Paste everything into context | 19.5M (impossible) | Doesn't fit | — |
| LLM summarization (Mem0, etc.) | ~650K | ~$507 | Nuance, exact quotes, reasoning |
| **AgentVault on startup** | **~250** | **$0** | Nothing — full history in ChromaDB |
| **AgentVault per search** | **~500-2,000** | **$0** | Nothing — returns exact matches |

**How it works under the hood:**

```
You: "How did we handle rate limiting in sphere-web?"
      │
      ▼ Claude calls vault_search via MCP
      │
      ▼ ChromaDB: embed query → HNSW index → find 5 nearest chunks
      │           filter by project="sphere-web"
      │           ~30ms, zero API calls
      │
      ▼ Returns ~1,500 tokens of relevant conversation
      │
Claude: "In your March 15 session, you implemented rate limiting
         using upstash/ratelimit with Redis..."
```

**10 searches in a session = ~15,000 tokens. That's 92% of a 200K context window still free for actual work.**

The search is local (ChromaDB + HNSW index on your machine), the embedding model runs locally (~80MB, downloaded once), and no data ever leaves your machine.

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
- **Auto-save** — new Claude Code sessions are automatically ingested via Stop hook

## Quick Start

```bash
# Install
pip install agentvault-memory

# Initialize — auto-detects AI tools, Obsidian, installs MCP + auto-save hook
agentvault init

# One-time bulk import of all history
agentvault ingest

# Search anything
agentvault search "why did we switch to GraphQL"
agentvault search "auth bug" --project sphere-web
agentvault search "rate limiting" --source claude-code

# Check status
agentvault status
```

That's it. Two commands to set up, then it runs automatically.

### What `init` does

1. **Detects AI tools** — scans for Claude Code, OpenCode, Codex, Cursor history
2. **Auto-detects Obsidian** — finds your vault by looking for `.obsidian/` in common locations
3. **Installs MCP server** — for every detected tool that supports MCP (Claude Code, Cursor, OpenCode)
4. **Installs auto-save hook** — Claude Code Stop hook that ingests new sessions automatically

No manual `--obsidian` flag or `mcp-install` needed. Everything is auto-detected.

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

Secrets (API keys, tokens, passwords, private keys, connection strings) are automatically redacted before storage.

## MCP Tools

After `init`, your AI tools have these search tools available via MCP:

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

If an Obsidian vault is detected (or provided via `--obsidian`), AgentVault writes browsable markdown:

```
obsidian-vault/
  agent-history/
    2026-04-09.md                      ← daily digest
    sphere-web/
      2026-04-09-4f66f16f.md           ← session transcript
    evaluate-explorer/
      2026-04-08-aa20d038.md
```

Each session file has YAML frontmatter (source, project, date, branch, tags) — searchable and linkable in Obsidian. No Obsidian? No problem — it's optional. ChromaDB search works without it.

## Supported Tools

| Tool | History | MCP | Auto-Save Hook |
|------|---------|-----|----------------|
| **Claude Code** | `~/.claude/projects/` (JSONL) | Yes | Yes |
| **OpenCode** | `~/.local/state/opencode/` (JSONL) | Yes | — |
| **Codex (OpenAI)** | `~/.codex/sessions/` (JSONL) | — | — |
| **Cursor** | `~/Library/Application Support/Cursor/` (SQLite) | Yes | — |
| ChatGPT | Planned (manual export) | — | — |

## Auto-Save (Future Sessions)

After `init`, a Claude Code Stop hook is installed that runs `agentvault ingest --source claude-code` after every session ends. New conversations are automatically indexed — no manual `ingest` needed.

For other tools, run `agentvault ingest` periodically or after significant work.

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
    ingester.py           ← Session → chunks (with secret redaction)
    redactor.py           ← Secret pattern detection (15 patterns)
  adapters/
    base.py               ← BaseAdapter interface
    claude_code.py        ← Claude Code JSONL parser
    opencode.py           ← OpenCode prompt history parser
    codex.py              ← Codex event-driven JSONL parser
    cursor.py             ← Cursor SQLite DB parser
  writers/
    obsidian.py           ← Markdown + daily digests
    chromadb_writer.py    ← Batch ingestion + dedup
```

## Security

- Secret redaction (API keys, tokens, passwords, private keys, connection strings) on all content before storage
- MCP server input validation (query length limits, top_k capped at 50, type checking)
- Path traversal protection in Obsidian writer
- ChromaDB + vault directories set to `0700` (owner-only)
- Obsidian files written with `0600` permissions
- Atomic config file writes with backups
- No telemetry, no cloud, no data leaves your machine

## Requirements

- Python 3.9+
- No API keys
- No Docker
- No internet after install (embedding model downloaded once, ~80MB)

## Inspiration

Inspired by [MemPalace](https://github.com/milla-jovovich/mempalace) — which proved that raw ChromaDB retrieval achieves 96.6% recall on LongMemEval with zero API calls. AgentVault applies this to the specific problem of multi-agent session consolidation for developers.

## License

MIT
