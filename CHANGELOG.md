# Changelog

All notable changes to AgentVault Memory. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow SemVer once 1.0 is reached.

## v1.0.0 — 2026-05-16

First stable release. CLI commands, MCP tool names, and the `Chunk` schema are now locked — anything breaking after this is a major bump.

### Added
- `agentvault archive` — TTL / auto-purge for old sessions. Walks chunks older than `--older-than-days` (default 180), condenses each session into one summary chunk with topic keywords + head/tail snippets, deletes the raw chunks. Idempotent via a `-archived` chunk-id sentinel. Supports `--project` and `--dry-run`.
- README rewrite covering every feature shipped through 1.0 (hybrid search, hooks, web viewer, pattern intelligence, archive).
- CHANGELOG.md (this file).
- Stability commitment section in README.

### Deferred
- Per-project Chroma sharding. The existing project-filter + FTS5 index already gives most of the cross-project ergonomics; a full sharded facade can land in 1.1 if real-world load warrants it.
- `agentvault tune`. The injection log shipped in v0.14.0 starts collecting the data; calibration logic needs evidence of which injected chunks were actually used by the assistant.
- Profile-driven performance pass. Hot-path optimization requires real-world 10k / 50k chunk vaults to measure against.

## v0.14.0 — 2026-05-16

- **Rule suggestion** (`agentvault rules` / `vault_rules`): regex set for `don't / never / always / stop / use X instead / prefer X over Y / make sure / I told you / remember to`. Greedy Jaccard clustering at 0.4 (looser than patterns.py because corrections have more verb-conjugation noise). Surfaces clusters spanning ≥ N distinct sessions as candidate CLAUDE.md rules.
- **Injection log** (`~/.agentvault/injection_log.jsonl`): every UserPromptSubmit injection writes one JSON line with `ts`, `prompt_hash` (SHA-1, never plaintext), `project`, `session_id`, `chunk_ids`. Capped at 1000 lines via prune-on-write, fails open.

## v0.13.0 — 2026-05-16

- **Web viewer** (`agentvault serve`, optional via `pip install agentvault-memory[ui]`). FastAPI app with inline HTML templates (no Jinja dep). Pages: home, search, projects, project detail (open TODOs + recurring problems for that project), session detail, `/api/stats` JSON. Binds 127.0.0.1 by default.

## v0.12.1 — 2026-05-16

- **Stale-TODO extractor** (`agentvault todos` / `vault_todos`). Regex set for TODO / FIXME / XXX / "we should…" / "let's add…" / "come back to…" / "need to…" / "would be nice…" / "add X later". Two-pass: extract, then mark resolved when a later chunk in the same project has a done-flavor line (added / fixed / shipped / completed / …) whose tokens overlap (Jaccard ≥ 0.4).

## v0.12.0 — 2026-05-16

- **Recurring-problem detector** (`agentvault patterns` / `vault_patterns`). Problem-line regex set (errors / exceptions / "doesn't work" / 5xx / tracebacks) → content tokens → greedy Jaccard clustering at 0.5 with growing centroid union-sets. Within-chunk dedupe prevents a single noisy chunk from inflating its own session count.

## v0.11.0 — 2026-05-16

- **Per-file context hook** (`agentvault file-context`, PreToolUse). When Claude is about to Read / Edit / Write / MultiEdit / NotebookEdit a file, surfaces a `## Past discussion of <path>` block. Searches by basename (full paths tokenize poorly under unicode61), throttled per-file via `~/.agentvault/file_context_throttle.json` (60s window, atomic writes, capped at 200 entries).

## v0.10.0 — 2026-05-16

- **Aider adapter**. Parses per-project `.aider.chat.history.md`. Multi-line user messages (contiguous `#### ` lines) joined into one human exchange; `> Applied edit to <path>` notices become `edit_file` ToolCalls and populate `files_touched`. Many in-file sessions concatenated under the latest header timestamp; `started_at` / `ended_at` span the whole file. Discovery walks from `history_path` (default `~`) with a depth cap and a prune list (`node_modules`, dot-dirs, `Library`, build outputs, etc.).

## v0.9.0 — 2026-05-16

- **Hybrid search**. New SQLite FTS5 index at `<persist_dir>/fts.sqlite` lives next to ChromaDB; both stores written in `add_chunks`. `VaultStore.search(mode=...)` supports `"semantic"` / `"keyword"` / `"hybrid"` (now the default). Hybrid runs both backends in parallel, min-max normalizes, and combines via weighted sum (default `semantic_weight=0.5`). Lazy migration backfills FTS5 from Chroma on first hybrid search. `vault_decisions` stays semantic (its synthetic query is decision-phrasing, not literal tokens).

## v0.8.1 — 2026-05-12

- Hotfix: long Claude Code sessions on big codebases produced 10+ MB Obsidian session files that hung Obsidian's indexer on startup. Writer now truncates each exchange at 2 KB, keeps only the first 30 + last 30 exchanges with a single skip marker for longer sessions, and hard-caps total transcript at 800 KB. Full content remains queryable via ChromaDB.

## v0.8.0 — 2026-04-27

- **SessionStart hook** (`agentvault session-start`): emits a wake-up summary + recent-activity block when a Claude Code session boots.
- **Time-decay re-ranking**: `VaultStore.search(time_decay=True)` reorders results by `relevance × exp(-age_days / 30)`. Wired into `vault_search_lite` and `vault_project_context`.

## v0.7.0 — 2026-04-23

- **UserPromptSubmit hook** (`agentvault inject-context`): injects the top relevant past chunks before each user prompt.

## v0.6.1 — 2026-04-15

- Fix: `AttributeError` when MCP server passed a `str` from JSON config to `VaultStore` (`'str' object has no attribute 'mkdir'`). `VaultStore` now coerces to `Path`.

## v0.6.0 — 2026-04-14

- Wake-up context (`vault_wake_up`) returns a ~50-token summary of recent activity; cheap to call once at session start.
- Default `min_relevance=0.25` filter on all MCP search tools to drop irrelevant matches without burning tokens.

## v0.5.0 — 2026-04-09

- Incremental `agentvault sync`. Per-source last-ingest timestamps in config.
- Richer `agentvault status`: per-source and per-project breakdown.
- Cursor project detection from session metadata.
- `agentvault export` (JSON + Markdown).

## v0.4.0 — 2026-04-08

- Session summaries (keyword extraction, no LLM).
- Decision log (`agentvault decisions` / `vault_decisions`).
- `agentvault forget` for targeted deletion.

## Earlier (pre-0.4)

Initial adapters for Claude Code / OpenCode / Codex / Cursor, ChromaDB ingest, Obsidian markdown output, MCP server, auto-detect `init`, secret redaction.
