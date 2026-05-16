# AgentVault Memory — Roadmap

Sequenced rollout of upcoming features. Each release is independently shippable, reversible, and small enough to validate before moving on. Current version: **v0.12.0**.

---

## v0.12.0 — Recurring-problem detector (✅ shipped 2026-05-16)

Surfaces problems the user has debugged multiple times across past sessions. Pattern intelligence shipped as two releases per the one-feature-per-release principle — patterns now (v0.12.0), stale-TODO extractor next (v0.12.1).

- New `agentvault/core/patterns.py`: regex-based problem-line detection (errors / exceptions / "doesn't work" / tracebacks / 5xx / etc.) + content-token extraction (stopword-stripped, ≥3 chars, ≥3 tokens per line).
- **Greedy single-link clustering by Jaccard similarity** (threshold 0.5). Each cluster keeps its growing union token-set as the centroid so vocabulary drift across descriptions still merges. Strict set-equality was tried first and over-discriminates real-world phrasing.
- Within-chunk dedupe: a chunk mentioning the same problem 5 times counts as one occurrence in that chunk's session (otherwise a single noisy chunk could fake a 3-session pattern).
- Threshold: clusters with `session_count >= min_sessions` (default 3) qualify.
- CLI: `agentvault patterns [--project X] [--min-sessions N] [--top N]` — rich table output.
- MCP tool: `vault_patterns(project?, min_sessions?)`.
- `chunk_limit=5000` cap on the scan so the command stays snappy on a 50k-chunk vault; raise via the function arg if needed.

---

## v0.11.0 — Per-file context (PreToolUse hook) (✅ shipped 2026-05-16)

Surfaces past discussion of a file just before Claude reads or edits it.

- New `agentvault file-context` CLI consumes a Claude Code PreToolUse hook event, pulls `tool_input.file_path` (also handles `path` / `notebook_path`), and emits a `## Past discussion of <path>` block via the hook envelope.
- Core logic in `agentvault/hooks/file_context.py` (`build_file_context`) — pure helper so it's testable without subprocess fixtures.
- Search uses the file's **basename** as the query against hybrid mode (v0.9.0). Basenames tokenize cleanly under FTS5 and most past discussions reference files by short name; full paths get stripped of `/` and `.` by the unicode61 tokenizer anyway.
- Project filter derived from `cwd` to keep noise down.
- Throttle: `~/.agentvault/file_context_throttle.json` records last-injected timestamp per path; same path within 60s is skipped. Atomic writes, mode 0600, auto-pruned (old entries dropped, capped at 200 entries).
- Hook installer registers `PreToolUse` with matcher `Read|Edit|Write|MultiEdit|NotebookEdit`. Wired into `init` and `mcp-install`. Skipped silently when `auto_inject = false`.
- Fails open — any exception in the hook exits 0 so Claude Code is never blocked.

---

## v0.10.0 — Aider adapter (✅ shipped 2026-05-16)

Adds Aider — the second-most-used AI coding CLI — as a first-class source.

- New `AiderAdapter` parses per-project `.aider.chat.history.md` files. Aider has no central history dir, so `discover_sessions` walks from `history_path` (default: `~`) with a depth cap and a prune list (`node_modules`, `.git`, `Library`, dot-dirs, etc.) so the walk doesn't grind through caches.
- Multi-line user messages (contiguous `#### ` lines) are joined into one human exchange. `> Applied edit to <path>` notices become `edit_file` ToolCalls on the preceding assistant turn and populate `files_touched`. Other `> ...` system lines are dropped.
- One file = one `AgentSession`. Aider re-uses one file across many sessions, so all chats in the file are concatenated under the latest header's timestamp; `started_at`/`ended_at` span the full file.
- Auto-detected in `agentvault init`, picked up by `agentvault ingest` and `agentvault sync`. Source label `aider` flows through `vault_status` / `vault_wake_up` automatically.

---

## v0.9.0 — Hybrid search (✅ shipped 2026-05-16)

Closes the keyword-recall gap with claude-mem so exact strings (function names, error codes, file paths) land cleanly.

- New `FTSIndex` (SQLite FTS5, BM25) lives at `<persist_dir>/fts.sqlite`, mirrored on every `add_chunks` write.
- `VaultStore.search(mode=...)` now supports `"semantic"` (Chroma only), `"keyword"` (FTS5 only), and `"hybrid"` (default). Hybrid runs both backends in parallel, min-max normalizes each, and combines via weighted sum (default `semantic_weight=0.5`, tunable).
- Lazy migration backfills FTS5 from Chroma on first hybrid/keyword search if it's behind — idempotent, one-shot per process.
- All `delete_*` paths propagate to FTS5.
- `vault_search`, `vault_search_lite`, `vault_project_context`, `vault_cross_reference` default to hybrid. `vault_decisions` stays semantic (its synthetic query is decision-phrasing, not literal tokens).

---

## v0.8.1 — Vault size caps (✅ shipped 2026-05-12)

Hotfix: long Claude Code sessions on big codebases produced 10+ MB markdown files that hung Obsidian's indexer and graph view on startup. Writer now:
- truncates each exchange at 2 KB,
- keeps only the first 30 + last 30 exchanges with a single skip marker when a session has more,
- hard-caps total transcript at 800 KB as a final safety net.

Full content remains queryable via ChromaDB. Existing oversized files in the vault are not touched by this change — clean them up manually or with `agentvault sync --rewrite` (future).

---

## v0.8.0 — Smart hooks (✅ shipped 2026-04-27)

- **SessionStart hook** (`agentvault session-start`): emits a wake-up summary + recent-activity block when a Claude Code session boots, so context is loaded without anyone having to call `vault_wake_up`.
- **UserPromptSubmit hook** (`agentvault inject-context`): injects the top relevant past chunks before each user prompt (added in v0.7.0, polished in v0.8.0).
- **Time-decay re-ranking**: `VaultStore.search(time_decay=True)` reorders results by `relevance × exp(-age_days / 30)` so a chat from yesterday outranks one from six months ago at equal relevance. Wired into `vault_search_lite` and `vault_project_context` MCP tools.

---

## v0.12.1 — Stale-TODO extractor (next)

**Goal:** surface unresolved "I'll come back to X" / "TODO: X" / "we should X" / "let's add later" from past chats, scoped to the current project.

- Regex + light NLP over chunk content; capture the TODO text, project, timestamp, session.
- Resolution heuristic: extract a 2–4 word noun phrase from each TODO; mark resolved when a later chunk in the same project mentions that phrase in a "done"-flavor context (added / fixed / shipped / completed). Crude but workable for v1.
- CLI: `agentvault todos [--project X] [--unresolved]`.
- Optional weekly digest written to Obsidian.

---

## v0.13.0 — Web viewer

**Goal:** a localhost UI to browse/search/filter the vault — what claude-mem does. Obsidian is great for read; web is better for cross-project search.

- New CLI: `agentvault serve [--port 3777]` — embedded FastAPI/Starlette server.
- Pages:
  - Search (FTS5 + vector, per-project filter, date range)
  - Project view (timeline + decisions + recurring patterns)
  - Session detail (full chunks, tool calls, file edits)
- Stats dashboard: chunks/sessions/sources, hit-rate, token savings.
- Single-binary launch: `pip install agentvault-memory[ui]` adds the small extra dep set.

---

## v0.14.0 — Self-improvement

**Goal:** make the harness learn from observed user behavior.

- **Skill / CLAUDE.md rule suggestion**: detect when the user repeats the same correction 3+ times across sessions (e.g., "don't add Co-Authored-By", "use 2-space indent"). Surface a one-liner: "Promote to CLAUDE.md? `agentvault promote-rule <id>`".
- **Hit-rate telemetry (local-only)**: track which injected contexts were referenced in subsequent assistant output. Tune `MIN_RELEVANCE` per-user from real data instead of the 0.35 default.
- **Feedback loop**: `agentvault tune` runs a calibration pass on the last N injections and writes recommended thresholds to config.

---

## v1.0.0 — Scale & polish

**Goal:** everything that has to be true to call this 1.0.

- **Per-project sharding**: separate Chroma collection per project, fanned out under one VaultStore facade. Search across all by default; scope by project optional.
- **TTL / auto-purge**: sessions older than `archive_after_days` (default 180) get summarized into a single condensed chunk; raw chunks moved to a cold-storage collection.
- **Documentation pass**: README, in-repo docs, MCP tool descriptions all updated. Migration guide.
- **Performance pass**: profile ingest + search at 10k / 50k chunks; optimize hot paths.
- **Stable APIs**: lock the CLI, MCP tool names, and `Chunk` schema. Anything breaking after this is a major bump.

---

## Operating principles

- **One feature per release.** Multiple features only if they're tightly coupled (e.g., session-start + time-decay).
- **Fail open.** Hooks must never block Claude Code. Any error → exit 0, no output.
- **Token budget.** Every hook output stays under ~150 tokens unless the user opts in.
- **Reversible.** Every feature has a config flag to disable.
- **No co-author line in commits.**
