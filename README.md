<div align="center">

<img src="https://raw.githubusercontent.com/sauravkalia/agentvault/main/assets/logo.png" alt="AgentVault Memory" width="280">

### Unified memory layer for AI coding agents

Searchable by humans (Obsidian) and by AI (MCP)

[![PyPI](https://img.shields.io/pypi/v/agentvault-memory?style=flat-square&color=6366f1)](https://pypi.org/project/agentvault-memory/)
[![Python](https://img.shields.io/pypi/pyversions/agentvault-memory?style=flat-square)](https://pypi.org/project/agentvault-memory/)
[![License](https://img.shields.io/github/license/sauravkalia/agentvault?style=flat-square)](LICENSE)

</div>

---

Every conversation you have across Claude Code, OpenCode, Codex, Cursor — all siloed. Start a new session and your agent has zero context from any of them. AgentVault Memory fixes that.

## The Problem

Developers now use 3-4 AI coding tools daily — Claude Code in one terminal, Cursor in the IDE, Codex for quick tasks, OpenCode for another project. Every decision, every debugging session, every architecture discussion happens in these conversations. Then the session ends and it's gone.

**6 months of daily AI use = ~19.5 million tokens of conversations.** That's every decision, every "we tried X and it failed because Y", every debugging session. All trapped in separate tools that don't talk to each other.

You open a new Claude Code session and ask *"how did we handle auth?"* — it has no idea. The answer is in a Cursor session from last month. Or a Codex session from last week. Or three different Claude Code sessions across two projects.

## Why AgentVault Memory

There are many AI memory tools — MemPalace, Mem0, Zep, Letta, Pieces. None of them solve this specific problem.

| | AgentVault Memory | MemPalace | Mem0 | Zep | Pieces | Claude Auto Dream |
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

**The core difference:** Other tools store what the AI *decides* to remember. AgentVault Memory reads the raw conversation history files that your tools already store on disk — every word, every decision, every debugging session — and makes it all searchable. Nothing is lost because nothing is summarized away.

## Token Efficiency

The obvious question: if you have 19.5M tokens of history, how do you use it without blowing up the context window?

**You don't load it.** AgentVault Memory uses vector search — it only retrieves what's relevant to your question. And it optimizes every response to minimize tokens.

| Approach | Tokens per search | Annual cost | What you lose |
|----------|:---:|:---:|---|
| Paste everything into context | 19.5M (impossible) | Doesn't fit | — |
| LLM summarization (Mem0, etc.) | ~650K | ~$507 | Nuance, exact quotes, reasoning |
| **AgentVault Memory (full search)** | **~800** | **$0** | Nothing |
| **AgentVault Memory (lite search)** | **~200** | **$0** | Nothing — summaries first, full on demand |

### Built-in Token Optimizations

Every MCP search response goes through 5 optimizations before reaching your AI:

| Optimization | What It Does | Token Savings |
|-------------|-------------|:---:|
| **Summary-first search** | `vault_search_lite` returns one-line summaries, not full content. AI fetches full content only for what it needs | **~80%** |
| **Tool noise stripping** | Removes `[Used tools: Read]`, `[Tools used: Edit]` artifacts | **10-15%** |
| **Code block truncation** | Long code blocks trimmed to 4 lines + `(truncated)` | **20-30%** |
| **Result deduplication** | Near-identical results from the same session are merged | **15-20%** |
| **Compact metadata** | One-line format instead of 4 separate lines per result | **75%** |

### How It Works

```
You: "How did we handle rate limiting?"
      │
      ▼ AI calls vault_search_lite (summaries only, ~200 tokens)
      │
      ▼ Sees: "#1 78% — my-saas-app | claude-code | 2026-03-15"
      │        "    Implemented rate limiting using upstash..."
      │
      ▼ AI calls vault_search for full details on result #1 (~300 tokens)
      │
      ▼ Total: ~500 tokens (vs ~1,500 without optimization)
```

**10 searches in a session = ~5,000 tokens. That's 97% of a 200K context window still free for actual work.**

Everything runs locally — ChromaDB + HNSW index on your machine, embedding model (~80MB, downloaded once), no data ever leaves your machine.

## How It Works

```
Terminal 1: Claude Code (project A)  ─┐
Terminal 2: Claude Code (project B)  ─┤
Terminal 3: OpenCode                 ─┼──→ AgentVault Memory ──→ ChromaDB (AI search)
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
agentvault search "auth bug" --project my-saas-app
agentvault search "rate limiting" --source claude-code

# Pattern intelligence — surface recurring problems, open TODOs, candidate rules
agentvault patterns --min-sessions 3
agentvault todos --unresolved
agentvault rules

# View decisions extracted from your conversations
agentvault decisions
agentvault decisions --project my-saas-app

# Browse the vault locally in your browser (requires `pip install agentvault-memory[ui]`)
agentvault serve  # → http://127.0.0.1:3777

# TTL — condense sessions older than N days into one summary chunk each
agentvault archive --older-than-days 180 --dry-run
agentvault archive --older-than-days 180

# Incremental sync — only new sessions since last run
agentvault sync

# Delete data you don't want
agentvault forget --project old-project
agentvault forget --source cursor

# Export your data
agentvault export backup.json
agentvault export report.md --format markdown --project my-saas-app

# Check status (with per-tool and per-project breakdown)
agentvault status
```

That's it. Two commands to set up, then it runs automatically.

### What `init` does

1. **Detects AI tools** — scans for Claude Code, OpenCode, Codex, Cursor, Aider history
2. **Auto-detects Obsidian** — finds your vault by looking for `.obsidian/` in common locations
3. **Installs MCP server** — for every detected tool that supports MCP (Claude Code, Cursor, OpenCode)
4. **Installs hooks** — Claude Code Stop (auto-save), UserPromptSubmit (context injection), SessionStart (wake-up), PreToolUse (per-file context surfacing)

No manual `--obsidian` flag or `mcp-install` needed. Everything is auto-detected.

## What Gets Indexed

From each session, AgentVault Memory extracts:

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

| Tool | What It Does | Tokens |
|------|-------------|:---:|
| `vault_wake_up` | **Call once at session start** — tiny context summary of recent projects and activity | **~50** |
| `vault_search_lite` | One-line summaries via hybrid (BM25 + vector) search. Use for initial scan | ~200 |
| `vault_search` | Full hybrid search with project / source / branch filters | ~800 |
| `vault_project_context` | "What have I done on project X recently?" — time-decay reranked | ~800 |
| `vault_cross_reference` | "Did I solve this problem before in another project?" | ~800 |
| `vault_decisions` | "What decisions did I make about auth?" | ~500 |
| `vault_patterns` | "What problems have I debugged multiple times?" — recurring-problem clusters | ~400 |
| `vault_todos` | "What was I supposed to come back to?" — open TODOs with resolution heuristic | ~500 |
| `vault_rules` | "What corrections do I keep repeating?" — candidate CLAUDE.md rules | ~400 |
| `vault_status` | Overview of indexed sessions and projects | ~100 |

All search tools default to **hybrid search** (FTS5 BM25 + ChromaDB cosine, normalized + weighted-sum combined) so exact strings — function names, error codes, file paths — land cleanly alongside semantic matches. Results below 25% relevance are filtered out automatically.

Your AI calls these automatically when you ask questions like:
- *"Remember that auth bug we fixed last week?"*
- *"How did we handle rate limiting in the other project?"*
- *"What decisions did I make about the database?"*

## Obsidian Integration

If an Obsidian vault is detected (or provided via `--obsidian`), AgentVault Memory writes browsable markdown:

```
obsidian-vault/
  agent-history/
    2026-04-09.md                      ← daily digest
    my-saas-app/
      2026-04-09-4f66f16f.md           ← session transcript
    my-api-server/
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
| **Aider** | per-project `.aider.chat.history.md` (Markdown) | — | — |
| ChatGPT | Planned (manual export) | — | — |

## Auto-Save (Future Sessions)

After `init`, a Claude Code Stop hook is installed that runs `agentvault ingest --source claude-code` after every session ends. New conversations are automatically indexed — no manual `ingest` needed.

For other tools, run `agentvault ingest` periodically or after significant work.

## Session Summaries

Every session is auto-summarized during ingestion using keyword extraction (no LLM needed). Summaries appear in Obsidian files and daily digests, making it easy to scan what each session was about without reading the full transcript.

## Decision Log

AgentVault Memory automatically extracts decisions from your conversations — "decided to use X", "chose Y over Z", "switching to W". These are surfaced via:

- **CLI:** `agentvault decisions` — view all extracted decisions, filter by project
- **MCP:** `vault_decisions` tool — your AI can query past decisions mid-session
- **Obsidian:** `## Key Decisions` section added to each session file

## Pattern Intelligence

Three heuristic detectors that turn session history into actionable signal:

- **Recurring problems** — `agentvault patterns` / `vault_patterns`. Greedy Jaccard clustering on problem-flavor lines (errors / exceptions / "doesn't work") across sessions. Surfaces any cluster spanning ≥ 3 distinct sessions — "you've debugged this kind of thing 4 times."
- **Stale TODOs** — `agentvault todos [--unresolved]` / `vault_todos`. Pulls out TODO / FIXME / "we should…" / "I'll come back to…" notes. Each TODO is marked resolved when a later chunk in the same project mentions wrapping it up (added / fixed / shipped / completed / …) with sufficient token overlap.
- **Candidate rules** — `agentvault rules` / `vault_rules`. Pulls repeated user corrections ("don't add Co-Authored-By", "always run lint", "use named exports instead of default") and surfaces clusters with ≥ 3 occurrences as candidates worth promoting to CLAUDE.md.

## Web Viewer

Optional localhost UI for browsing the vault — install with `pip install agentvault-memory[ui]`.

```bash
agentvault serve   # → http://127.0.0.1:3777
```

Pages: home (stats + search box), `/search` (hybrid search results), `/projects` (list), `/projects/{name}` (sessions + open TODOs + recurring problems for that project), `/sessions/{id}` (all chunks for one session). Binds to loopback only by default.

## TTL / Archive

Long-running vaults get big. `agentvault archive --older-than-days 180` walks every session whose newest chunk is older than the cutoff and condenses it into a single chunk carrying the session's topic keywords + head/tail snippets. Idempotent (already-archived sessions are skipped via a `-archived` chunk-id sentinel), supports `--dry-run` and `--project`.

The trade: vector recall on archived sessions drops to one chunk, but session-level facts ("we worked on X for Y in March") survive and the store stays small.

## Forget (Data Control)

Delete any data you don't want in the vault:

```bash
agentvault forget --session <id>     # one session
agentvault forget --project old-app  # all sessions for a project
agentvault forget --source cursor    # all sessions from a tool
agentvault forget --all              # wipe everything (with confirmation)
```

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
  web.py                  ← FastAPI viewer (optional, [ui] extras)
  core/
    schema.py             ← AgentSession, Exchange, Chunk
    store.py              ← ChromaDB + FTS5 facade, hybrid search
    fts_index.py          ← SQLite FTS5 keyword index
    ingester.py           ← Session → chunks (with secret redaction)
    redactor.py           ← Secret pattern detection (15 patterns)
    summarizer.py         ← Keyword extraction summaries
    decisions.py          ← Decision extraction
    patterns.py           ← Recurring-problem clustering
    todos.py              ← TODO extraction + resolution heuristic
    rules.py              ← Repeated-correction clustering
    archive.py            ← TTL summarize-and-purge
  adapters/
    base.py               ← BaseAdapter interface
    claude_code.py        ← Claude Code JSONL parser
    opencode.py           ← OpenCode prompt history parser
    codex.py              ← Codex event-driven JSONL parser
    cursor.py             ← Cursor SQLite DB parser
    aider.py              ← Aider .aider.chat.history.md parser
  hooks/
    file_context.py       ← PreToolUse per-file context helper
    injection_log.py      ← UserPromptSubmit injection log
  writers/
    obsidian.py           ← Markdown + daily digests
    chromadb_writer.py    ← Batch ingestion + dedup
```

## Stability (v1.0)

As of v1.0.0, the following are considered stable and won't break in 1.x:

- **CLI commands**: `init`, `ingest`, `sync`, `search`, `decisions`, `patterns`, `todos`, `rules`, `archive`, `serve`, `forget`, `export`, `status`, `mcp-install`, plus the hook commands (`session-start`, `inject-context`, `file-context`).
- **MCP tool names**: `vault_wake_up`, `vault_search`, `vault_search_lite`, `vault_project_context`, `vault_cross_reference`, `vault_decisions`, `vault_patterns`, `vault_todos`, `vault_rules`, `vault_status`.
- **`Chunk` schema** in `agentvault.core.schema`.
- **Config file shape** at `~/.agentvault/config.json`.

Any breaking change to the above after 1.0.0 will bump the major version. New fields / new commands / new tools are additive and may land in any minor release.

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

Inspired by [MemPalace](https://github.com/milla-jovovich/mempalace) — which proved that raw ChromaDB retrieval achieves 96.6% recall on LongMemEval with zero API calls. AgentVault Memory applies this to the specific problem of multi-agent session consolidation for developers.

## License

MIT
