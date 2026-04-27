# AgentVault Memory — Roadmap

Sequenced rollout of upcoming features. Each release is independently shippable, reversible, and small enough to validate before moving on. Current version: **v0.8.0**.

---

## v0.8.0 — Smart hooks (✅ shipped 2026-04-27)

- **SessionStart hook** (`agentvault session-start`): emits a wake-up summary + recent-activity block when a Claude Code session boots, so context is loaded without anyone having to call `vault_wake_up`.
- **UserPromptSubmit hook** (`agentvault inject-context`): injects the top relevant past chunks before each user prompt (added in v0.7.0, polished in v0.8.0).
- **Time-decay re-ranking**: `VaultStore.search(time_decay=True)` reorders results by `relevance × exp(-age_days / 30)` so a chat from yesterday outranks one from six months ago at equal relevance. Wired into `vault_search_lite` and `vault_project_context` MCP tools.

---

## v0.9.0 — Search quality (next)

**Goal:** close the keyword-search gap with claude-mem so exact strings (function names, error codes, file paths) land cleanly.

- Add SQLite FTS5 index alongside ChromaDB. On every `add_chunks` write to both stores.
- New `VaultStore.search(mode="hybrid")` that:
  - Runs FTS5 (BM25) and Chroma (cosine) in parallel
  - Normalizes scores (z-score or min-max)
  - Combines with weighted sum (default 0.5/0.5; tunable)
  - Deduplicates and re-ranks
- Migration: lazy-build FTS5 from existing chunks on first hybrid search; idempotent.
- Update `vault_search` and `vault_search_lite` to default to hybrid.
- Tests: keyword-only queries (e.g., `useAuthProvider`) should beat semantic-only on exact matches.

---

## v0.10.0 — Aider adapter

**Goal:** add the second-most-used AI coding CLI as a first-class source.

- Parse Aider's chat history (markdown + JSON sidecar) from `~/.aider/` or per-project `.aider.chat.history.md`.
- Map Aider's user/assistant turns + file edits into the existing `Chunk` schema.
- Add `agentvault ingest --source aider`.
- `agentvault init` auto-detects Aider installation.
- New source label `aider` shown in `vault_status` / `vault_wake_up`.

---

## v0.11.0 — Per-file context (PreToolUse hook)

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
