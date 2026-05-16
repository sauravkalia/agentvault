# AgentVault Memory — Roadmap

Sequenced rollout of upcoming features. Each release is independently shippable, reversible, and small enough to validate before moving on. Current version: **v0.10.0**.

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

## v0.11.0 — Per-file context (PreToolUse hook, next)

**Goal:** when Claude is about to read/edit a file, surface what was previously discussed about that file.

- New CLI: `agentvault file-context` (reads PreToolUse hook event, extracts `tool_input.file_path`).
- Search vault for chunks mentioning that path (literal match + semantic).
- Emit a short `## Past discussion of {path}` block via the hook envelope.
- Throttle: skip if file was injected in the last N prompts (avoid duplication with `inject-context`).
- Hook installer auto-registers PreToolUse with matchers `Read`, `Edit`, `Write`.

---

## v0.12.0 — Pattern intelligence

**Goal:** surface patterns across sessions, not just retrieve them.

- **Recurring-problem detector**: cluster chunks by content fingerprint + project; flag any cluster with ≥3 occurrences across ≥3 sessions. Output: "you've debugged 'undefined redirect' 4 times — last fix was on 2026-04-21."
  - CLI: `agentvault patterns [--project X]`
  - MCP tool: `vault_patterns`
- **Stale-TODO extractor**: regex + light NLP for "I'll come back to", "TODO:", "we should", "let's add later"; mark resolved when the same project sees a follow-up commit/discussion mentioning the same noun phrase.
  - CLI: `agentvault todos [--unresolved]`
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
