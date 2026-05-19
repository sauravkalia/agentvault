# AgentVault Memory — Architecture & Developer Guide

This is the deep-dive for contributors. The root [`README.md`](../README.md) is user-facing — install, configure, use. This document explains how the code works under the hood.

---

## Table of contents

1. [Overview](#overview)
2. [Project structure](#project-structure)
3. [Core schema](#core-schema)
4. [Write path — ingestion](#write-path--ingestion)
5. [Read path — search](#read-path--search)
6. [Hybrid search algorithm](#hybrid-search-algorithm)
7. [Adapters — how to add a new tool](#adapters--how-to-add-a-new-tool)
8. [MCP server](#mcp-server)
9. [Claude Code hooks](#claude-code-hooks)
10. [Heuristic detectors](#heuristic-detectors)
11. [Configuration](#configuration)
12. [Testing](#testing)
13. [Contributing](#contributing)

---

## Overview

AgentVault Memory is a local-first memory layer that reads raw conversation history written to disk by AI coding agents (Claude Code, Cursor, Codex, OpenCode) and makes it queryable by humans (Obsidian) and AI (MCP).

**Design principles:**

- **Local-first.** No cloud calls. No API keys. The embedding model runs on CPU. Vector store is local (ChromaDB persistent client). Keyword index is local (SQLite FTS5).
- **Fail open.** Hooks must never block Claude Code. Any error in a hook → exit 0, no output, Claude continues normally.
- **One feature per release.** Each release is independently shippable, reversible, and small enough to validate.
- **No co-author lines in commits.**
- **Reversible.** Every feature has a config flag to disable.

**Two pipelines, two output surfaces:**

```
Write path:                                Read path:

native history file                        user query
       │                                        │
       ▼                                        ▼
   adapter parse                          embed query
       │                                        │
       ▼                                  ┌─────┴─────┐
   AgentSession → Chunks                  ▼           ▼
       │                                Chroma     FTS5
       ▼                                (vector)   (BM25)
   redact secrets                          │           │
       │                                   └─────┬─────┘
       ▼                                         ▼
   embed (MiniLM-L6-v2)                   normalize + fuse
       │                                         │
       ▼                                         ▼
   ┌───┴───┐                                top K results
   ▼       ▼                                     │
 Chroma   FTS5                          ┌────────┼────────┐
                                        ▼        ▼        ▼
                                       MCP      CLI      Web
```

---

## Project structure

```
agentvault/
  cli.py                   CLI entry point (click + rich)
  config.py                ~/.agentvault/config.json read/write
  mcp_server.py            MCP server (stdio transport) — 10 vault_* tools
  web.py                   FastAPI viewer (optional [ui] extras)
  core/
    schema.py              AgentSession, Exchange, Chunk dataclasses
    store.py               VaultStore — ChromaDB + FTS5 facade, hybrid search
    fts_index.py           SQLite FTS5 keyword index
    ingester.py            Session → Chunks (with secret redaction)
    redactor.py            15 regex patterns for secret detection
    summarizer.py          Keyword extraction summaries (no LLM)
    decisions.py           Decision extraction from chunks
    patterns.py            Recurring-problem clustering
    todos.py               TODO extraction + done-marker resolution
    rules.py               Repeated-correction clustering
    archive.py             TTL — condense old sessions to summary chunks
  adapters/
    base.py                BaseAdapter interface
    claude_code.py         Claude Code JSONL parser
    cursor.py              Cursor SQLite parser
    codex.py               Codex event-driven JSONL parser
    opencode.py            OpenCode JSONL parser
    aider.py               Aider Markdown parser
  hooks/
    file_context.py        PreToolUse per-file context helper
    injection_log.py       UserPromptSubmit injection log writer
  writers/
    obsidian.py            Markdown + daily digests + YAML frontmatter
    chromadb_writer.py     Batch ingestion + dedup
tests/                     pytest suite — one file per module
docs/
  ARCHITECTURE.md          This file
```

---

## Core schema

Three dataclasses define the normalized internal format. Every adapter must produce these shapes; the rest of the pipeline only ever sees them.

```python
# core/schema.py

@dataclass
class AgentSession:
    source: str                 # "claude-code" | "cursor" | "codex" | "opencode" | "aider"
    session_id: str             # stable per-session ID
    project: str | None         # extracted from cwd / metadata
    git_branch: str | None
    started_at: datetime
    ended_at: datetime
    exchanges: list[Exchange]

@dataclass
class Exchange:
    user_message: str
    assistant_response: str
    tool_calls: list[ToolCall]
    timestamp: datetime
    files_touched: list[str]

@dataclass
class Chunk:
    id: str                     # f"{session_id}-{chunk_index}"
    session_id: str
    project: str
    source: str
    git_branch: str
    timestamp: str              # ISO 8601 UTC
    chunk_index: int            # order within session
    content: str                # flattened user msg + assistant reply + tool calls
    files_touched: list[str]
```

The schema is **locked at v1.0** — additive changes only without a major version bump.

---

## Write path — ingestion

Triggered automatically by the Claude Code `Stop` hook, or manually via `agentvault sync` / `agentvault ingest` for other tools.

### 1. Adapter reads native file

Each tool's history lives at a known path:

| Tool | Path | Format |
|---|---|---|
| Claude Code | `~/.claude/projects/<project-hash>/<uuid>.jsonl` | JSONL |
| Cursor | `~/Library/Application Support/Cursor/User/workspaceStorage/*/state.vscdb` | SQLite |
| Codex | `~/.codex/sessions/<date>/<id>.jsonl` | JSONL |
| OpenCode | `~/.local/state/opencode/<session>.jsonl` | JSONL |
| Aider | per-project `.aider.chat.history.md` | Markdown |

### 2. Parse to AgentSession

The adapter normalizes its native format into the common `AgentSession` dataclass. All schema-drift complexity lives inside the adapter's `parse_session()` method. The blast radius of any single tool's format change is one file.

### 3. Chunk per exchange

`Ingester` walks `session.exchanges` and emits one `Chunk` per exchange. Each chunk's content is the flattened text: user message + assistant reply + tool calls.

### 4. Secret redaction (15 patterns)

Before content is stored, `core/redactor.py` scrubs:

- AWS / GCP / Azure access keys
- OpenAI / Anthropic / Cohere API tokens
- GitHub PATs (`ghp_`, `gho_`, etc.)
- Slack tokens (`xoxp-`, `xoxb-`)
- Stripe keys (`sk_live_`, `sk_test_`)
- JWTs (`eyJ...`)
- Basic-auth URLs (`https://user:pass@...`)
- Private keys (`-----BEGIN ... PRIVATE KEY-----`)
- Connection strings (`postgres://`, `mongodb+srv://`, etc.)
- Generic high-entropy strings

Matches are replaced with typed placeholders (e.g., `[REDACTED:aws-key]`) so search can still find context without exposing the secret.

### 5. Embed

| Property | Value |
|---|---|
| Model | `sentence-transformers/all-MiniLM-L6-v2` |
| Output dimension | 384 |
| Disk size | ~80 MB |
| Device | CPU (no GPU required) |
| Latency | ~1-5 ms per chunk |
| License | Apache 2.0 |

Downloaded once on first use, cached at `~/.cache/huggingface/hub/`. Never leaves the machine after that.

### 6. Store in both backends (parallel)

**ChromaDB** at `~/.agentvault/chromadb/`:
- Persistent local mode (no server)
- HNSW index, `hnsw:space=cosine`
- Metadata: project, source, git_branch, session_id, timestamp, chunk_index

**SQLite FTS5** at `~/.agentvault/chromadb/fts.sqlite`:
- Tokenizer: `unicode61 remove_diacritics 2`
- BM25 ranking
- Same metadata columns so filters behave identically

If either write fails, the chunk is treated as not-ingested (we avoid partial state).

### 7. Obsidian writer (optional)

If an Obsidian vault is detected during `agentvault init`, `writers/obsidian.py` also emits markdown:

```
<obsidian-vault>/agent-history/
  2026-05-19.md                      ← daily digest
  <project-name>/
    2026-05-19-<session-hash>.md     ← full session transcript
```

Each file gets YAML frontmatter (source, project, date, branch, tags). File mode `0600`.

---

## Read path — search

Entry point: `VaultStore.search()` in `core/store.py`.

```python
store.search(
    query="refresh token rotation",
    top_k=5,
    project=None,                # optional filter
    source=None,                 # optional filter
    git_branch=None,             # optional filter
    min_relevance=0.0,           # optional cutoff (semantic only)
    time_decay=False,            # optional rerank
    half_life_days=30.0,
    mode="hybrid",               # "semantic" | "keyword" | "hybrid"
    semantic_weight=0.5,         # 0..1 for hybrid mode
)
```

### Steps

1. **Embed the query** (semantic/hybrid only) — same model as ingestion, so vector spaces match
2. **Fan out to both backends in parallel** — ChromaDB HNSW + SQLite FTS5 BM25
3. **3× oversample** — fetch `top_k * 3` from each side so misses don't unfairly penalize
4. **Min-max normalize** each result list to `[0, 1]`
5. **Weighted-sum combine** — default `semantic_weight=0.5`
6. **Optional time-decay rerank** — `score *= exp(-age_days / half_life_days)`
7. **Optional min_relevance filter** — drops semantic results below the threshold
8. **Sort by score, return top K**

Total round-trip on a 2.5k-chunk vault: ~30-50 ms. Zero network calls.

---

## Hybrid search algorithm

The fusion logic in `_hybrid()` (`core/store.py`):

```python
fetch_k = max(top_k * 3, 10)
sem_hits = self._semantic(query, fetch_k, ...)   # ChromaDB
kw_hits  = self.fts.search(query, top_k=fetch_k, ...)  # FTS5

# Normalize semantic: 1 - cosine_distance, then min-max over this query's pool
sem_raw = {h["id"]: (1 - h["distance"]) for h in sem_hits}
sem_norm = _min_max_normalize(sem_raw)

# Normalize keyword: BM25 is lower-is-better, invert then min-max
kw_raw = {h["id"]: -h["bm25"] for h in kw_hits}
kw_norm = _min_max_normalize(kw_raw)

# Combine
kw_weight = 1.0 - semantic_weight
for cid in all_ids:
    s = sem_norm.get(cid, 0.0)   # 0 if not in semantic side's top
    k = kw_norm.get(cid, 0.0)    # 0 if not in keyword side's top
    score = semantic_weight * s + kw_weight * k
```

**Why this design:**

- **3× oversample** — a chunk strong on one side but missing from the other's top-K would score 0 on that dimension and get unfairly penalized. Fetching more candidates per side mitigates this.
- **Min-max not z-score** — bounded `[0, 1]` makes the weighted-sum interpretable. Z-score would let outliers dominate.
- **Edge case** — when all values in a list are identical, every result gets `1.0` (we don't divide by zero).

**Tuning:** the default `semantic_weight=0.5` is set by feel, not formal A/B. Per-call tunable. v1.1's `agentvault tune` will calibrate from the injection log (which chunks the assistant actually referenced after injection).

---

## Adapters — how to add a new tool

Implement `BaseAdapter` (4 methods):

```python
from pathlib import Path
from agentvault.adapters.base import BaseAdapter
from agentvault.core.schema import AgentSession

class MyToolAdapter(BaseAdapter):
    name = "my-tool"
    description = "My new AI coding tool"

    def default_history_path(self) -> Path:
        return Path.home() / ".my-tool" / "history"

    def detect(self) -> bool:
        return self.history_path.exists()

    def discover_sessions(self) -> list[Path]:
        return list(self.history_path.glob("*.jsonl"))

    def parse_session(self, path: Path) -> AgentSession | None:
        # Read the file, return an AgentSession or None if unparseable
        ...
```

**Defensive coding patterns** every adapter should use:

- **Default-with-fallback on every field**: `meta.get("project", "unknown")`, never `meta["project"]`
- **Skip-on-failure per session**, not per file: if one session in a JSONL file is malformed, log it and move on
- **Tolerate unknown event types**: `continue` on anything we don't recognize, log at DEBUG level
- **Return `None` from `parse_session()`** if the session can't be parsed — pipeline keeps running for other sessions

Then register the adapter in `config.py` defaults and add to `cli.py`'s adapter map.

---

## MCP server

`mcp_server.py` exposes 10 tools over stdio JSON-RPC. Any MCP client (Claude Code, Cursor, OpenCode) can call them.

| Tool | Returns |
|---|---|
| `vault_wake_up` | ~50-token recent-activity summary |
| `vault_search_lite` | One-line summaries via hybrid search (~200 tokens) |
| `vault_search` | Full hybrid search results (~800 tokens) |
| `vault_project_context` | Recent work on a specific project (time-decay reranked) |
| `vault_cross_reference` | "Did I solve this in another project?" |
| `vault_decisions` | Decisions extracted from past chats |
| `vault_patterns` | Recurring-problem clusters |
| `vault_todos` | Open TODOs with done-marker resolution |
| `vault_rules` | Repeated-correction clusters (CLAUDE.md candidates) |
| `vault_status` | Sessions / chunks / sources overview |

**Default behaviors:**
- `min_relevance=0.25` on all search tools (drops irrelevant matches)
- Search tools default to `mode="hybrid"`
- `vault_decisions` stays semantic-only (its synthetic query is decision-phrasing, not literal tokens)

**Input validation:** query length capped at 10k chars, `top_k` capped at 50.

---

## Claude Code hooks

Each hook receives a JSON event on stdin and emits JSON on stdout. **All hooks fail open** — any exception → exit 0, no output → Claude continues normally.

| Hook | When | What it does | Token budget |
|---|---|---|---|
| `SessionStart` | New Claude Code session | Calls `vault_wake_up` → injects recent-activity summary | ~150 |
| `UserPromptSubmit` | Before each user prompt | Calls `vault_search_lite` → injects top-3 relevant past chunks | ~150 |
| `PreToolUse` | Before Read/Edit/Write/MultiEdit/NotebookEdit | Surfaces `## Past discussion of <path>` if file's been discussed | ~150 |
| `Stop` | Session ends | Runs `agentvault ingest --source claude-code` to backfill new session | (silent) |

**Hook installation** happens during `agentvault init` / `agentvault mcp-install`. Disable via config flag `auto_inject: false`.

**Throttling:** `PreToolUse` uses `~/.agentvault/file_context_throttle.json` to avoid re-injecting the same file context within 60 seconds.

**Injection logging:** every `UserPromptSubmit` injection writes one line to `~/.agentvault/injection_log.jsonl` (capped at 1000 lines, prune-on-write). Stores `ts`, `prompt_hash` (SHA-1, never plaintext), `project`, `session_id`, `chunk_ids`. Forms the dataset for the future `agentvault tune` command.

---

## Heuristic detectors

Three pure-Python detectors live in `core/patterns.py`, `core/todos.py`, `core/rules.py`. **No LLM at runtime** — regex + tokenization + Jaccard clustering.

### Patterns — recurring problems

1. Pull up to 5000 chunks
2. Regex-extract lines matching problem-flavor words: `error`, `exception`, `traceback`, `critical`, `bug`, `broken`, `failed`, `doesn't work`, `5xx`, `panic`
3. Tokenize, strip stopwords, require ≥3 content tokens
4. Greedy Jaccard clustering at **threshold 0.5** with growing union centroid
5. Within-chunk dedupe (one chunk = 1 occurrence)
6. Surface clusters spanning ≥ `min_sessions` distinct sessions

### TODOs — extraction + resolution

**Pass 1 (extract):** regex match TODO/FIXME/XXX/we-should/come-back-to/let's-add/need-to/would-be-nice/gonna phrasings. Trim, dedupe within-chunk via Jaccard ≥ 0.7.

**Pass 2 (resolve):** sort chunks by timestamp. For each TODO, walk later chunks in the same project. Look for done-flavor lines (added/fixed/shipped/completed/implemented/landed/merged). If Jaccard ≥ **0.4** → mark resolved.

### Rules — repeated corrections

Same shape as patterns but for corrective phrasings (`don't`, `never`, `always`, `stop`, `use X instead`, `prefer X over Y`, `avoid`, `make sure`, `I told you`, `remember to`).

Jaccard threshold is **0.4** (looser than patterns at 0.5) because corrections have more verb-conjugation noise.

**Known v1.0 limitation:** all three detectors match template lines from skill outputs / CLAUDE.md as if they were real signal. v1.1 will add a template-noise filter (checkbox lines, severity legends, file-path tokens).

---

## Configuration

All config lives at `~/.agentvault/config.json`:

```json
{
  "obsidian_vault": "/path/to/vault",       // optional
  "adapters": {
    "claude-code": { "enabled": true, "history_path": "..." },
    "cursor":      { "enabled": true, "history_path": "..." },
    "codex":       { "enabled": true, "history_path": "..." },
    "opencode":    { "enabled": true, "history_path": "..." },
    "aider":       { "enabled": true, "history_path": "..." }
  },
  "last_ingest": {
    "claude-code": "2026-05-19T12:34:56Z",  // per-source incremental sync
    ...
  },
  "auto_inject": true,                      // UserPromptSubmit hook toggle
  "file_context": true                      // PreToolUse hook toggle
}
```

Atomic writes via tempfile + rename. File mode `0600`.

The vault data dir at `~/.agentvault/chromadb/` is `chmod 0700` (owner-only).

---

## Testing

```bash
# Run the suite
pytest tests/

# Lint
ruff check agentvault/ tests/

# Type-check (optional, not in CI yet)
mypy agentvault/
```

**Test conventions:**

- One test file per source module (`test_<module>.py`)
- Use `tmp_path` fixture for filesystem isolation
- Mock the embedding model in unit tests — use real ChromaDB in integration tests
- `pytest.importorskip("fastapi")` for web tests (skips if `[ui]` extras not installed)
- Adapter tests use minimal fixture files under `tests/fixtures/<adapter>/`

---

## Contributing

1. **Open an issue first** for non-trivial changes — easier to align on approach than to redo a PR
2. **Follow existing patterns** — adapter interface, defensive parsing, fail-open hooks
3. **One feature per release** — if your PR ships two things, split them
4. **Add tests** — at minimum, one test per public function
5. **Run `ruff check`** before pushing
6. **No co-author lines in commits** — sole-author commits keep the history clean
7. **Update CHANGELOG.md** for user-visible changes
8. **Bump version in `pyproject.toml` and `agentvault/__init__.py`** for releases

### Architectural decisions worth keeping

- **No LLM at runtime.** Embedding model only. Keeps install simple and cost zero.
- **No cloud dependencies.** ChromaDB persistent client (no server), SQLite (built-in), sentence-transformers (CPU). Local-first is the moat.
- **Fail-open hooks.** Any hook error → exit 0. Claude Code must never be blocked by AgentVault.
- **Schema locked at 1.0.** Additive changes only. Major version bump required for breaking changes.

### Where to look first when something breaks

| Symptom | Likely file |
|---|---|
| Search returns nothing | `core/store.py` (`_hybrid()`, `_ensure_fts_migrated()`) |
| New session not auto-saved | `agentvault init` Stop hook registration, or check `~/.claude/settings.json` |
| MCP tools missing in Claude Code | `~/.claude.json` MCP config; run `agentvault mcp-install` |
| Hook output too large | Each hook should cap at ~150 tokens; check the formatter |
| Web viewer 500s | `web.py` — also confirm `[ui]` extras installed |
| Embedding model download stuck | Pre-warm with `agentvault search "hello" --top-k 1` |

---

## Further reading

- Root [`README.md`](../README.md) — user-facing install + usage
- [`CHANGELOG.md`](../CHANGELOG.md) — full release history from v0.4.0 onward
- [`PLAN.md`](../PLAN.md) — roadmap (now mostly historical, ships through v1.0.0)
- [Model Context Protocol spec](https://modelcontextprotocol.io) — for understanding the MCP surface
