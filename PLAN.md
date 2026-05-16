# AgentVault Memory — Roadmap

Sequenced rollout of upcoming features. Each release is independently shippable, reversible, and small enough to validate before moving on. Current version: **v1.0.0**.

---

## v1.0.0 — Scale & polish (✅ shipped 2026-05-16)

First stable release — CLI commands, MCP tool names, and the `Chunk` schema are now locked.

- **TTL / archive** (`agentvault/core/archive.py`, `agentvault archive` CLI). Walks chunks older than `--older-than-days` (default 180), condenses each session into one summary chunk (topic keywords from `_extract_keywords` + head/tail snippets), deletes the raw chunks. Idempotent via a `-archived` chunk-id sentinel. Supports `--project` and `--dry-run`. Deletes propagate to FTS5 via the existing VaultStore facade.
- **Documentation pass**: README rewrite covering hybrid search, hooks, web viewer, pattern intelligence, archive. New CHANGELOG.md with every release back to v0.4.0. New Stability section in README declaring the API surface that's locked.
- **PyPI classifier** flipped from `Development Status :: 3 - Alpha` to `5 - Production/Stable`.

### Deferred to a later release (explicitly out of scope for 1.0)

- **Per-project Chroma sharding**. The existing project filter + FTS5 index already gives most of the cross-project ergonomics; a sharded facade is worth doing only if real-world load shows it matters. → 1.1 candidate.
- **`agentvault tune`**. v0.14.0 started recording injection events in `~/.agentvault/injection_log.jsonl`. Calibration logic needs evidence of which injected chunks the assistant actually used — either a Stop-hook scan of the assistant's output or per-tool integration. → 1.1+.
- **Profile-driven performance pass**. Hot-path optimization needs real 10k / 50k chunk vaults to measure against, not synthetic benchmarks. → ongoing.

---

## v0.14.0 — Rule suggestions + injection log (✅ shipped 2026-05-16)

Two pieces of the original "self-improvement" plan. The third — `agentvault tune` — needs more data to be useful, so it's deferred; the injection log starts collecting that data now.

- **Rule suggestion** (`agentvault/core/rules.py`): regex set for `don't / never / always / stop doing / use X instead / prefer X over Y / avoid / make sure / I told you / remember to`. Greedy Jaccard clustering at threshold 0.4 (looser than patterns.py because corrective phrasings have more verb-conjugation noise). Any cluster spanning ≥ `min_occurrences` distinct sessions surfaces as a candidate the user might want to lift into CLAUDE.md.
- CLI: `agentvault rules [--project X] [--min-occurrences N] [--top N]` — rich table.
- MCP tool: `vault_rules(project?, min_occurrences?)` — agents can fetch likely-honored conventions before starting work.
- **Injection log** (`agentvault/hooks/injection_log.py`): every `UserPromptSubmit` injection appends one JSON line to `~/.agentvault/injection_log.jsonl` with `ts`, `prompt_hash` (SHA-1, first 16 chars — never plaintext), `project`, `session_id`, `chunk_ids`. Best-effort, fails open, capped at 1000 lines via prune-on-write. Forms the dataset for a future `agentvault tune` command.
- `tune` itself deferred — needs evidence of which injected chunks were actually referenced by the assistant, which requires either a Stop hook that scans output or per-tool integration. Out of scope for v0.14.

---

## v0.13.0 — Web viewer (✅ shipped 2026-05-16)

Localhost UI to browse / search / filter the vault — what claude-mem does. Obsidian is good for read-only browsing, web is better for cross-project search and following session/project links.

- New CLI: `agentvault serve [--host 127.0.0.1] [--port 3777]`. Binds to loopback by default so the viewer never accidentally goes onto the network.
- Routes (FastAPI, inline HTML rendered with `html.escape`, no Jinja dep):
  - `GET /` — stats summary + nav + inline search box.
  - `GET /search?q=...&project=...` — hybrid search (mode=hybrid from v0.9.0), results as cards.
  - `GET /projects` — project list with chunk counts.
  - `GET /projects/{name}` — recent activity, open TODOs, recurring problems (lower `min_sessions=2` for narrower per-project view).
  - `GET /sessions/{id}` — every chunk for one session, ordered by `chunk_index`.
  - `GET /api/stats` — JSON stats endpoint for ad-hoc scripts.
- Optional install: `pip install agentvault-memory[ui]` adds `fastapi` + `uvicorn` only. The core install stays slim.
- Tests use `fastapi.testclient.TestClient` and a `FakeStore`; module is `pytest.importorskip`-gated so the suite still runs cleanly when the extras aren't installed.

---

## v0.12.1 — Stale-TODO extractor (✅ shipped 2026-05-16)

Companion to v0.12.0's pattern intelligence. Surfaces unresolved "we should…" / TODO / FIXME / "come back to" notes from past chats with a resolution heuristic so the user sees what they actually still owe themselves.

- New `agentvault/core/todos.py`: regex set for TODO/FIXME/XXX/we-should/come-back-to/let's-add/would-be-nice/need-to/gonna/add-X-later phrasings. Each match's body is captured, trimmed, deduped within-chunk via Jaccard ≥ 0.7.
- Two-pass resolution: chunks are sorted by timestamp; for each TODO, scan only later chunks in the **same project** for a done-flavor line (added / fixed / shipped / completed / implemented / landed / merged / finished / resolved / wrapped up / took care of) whose content tokens Jaccard ≥ 0.4 with the TODO's tokens. First match wins.
- CLI: `agentvault todos [--project X] [--unresolved] [--top N]` — rich table with status column.
- MCP tool: `vault_todos(project?, only_unresolved?)`.
- `chunk_limit=5000` keeps the scan bounded on large vaults.
- Obsidian weekly digest deferred — easy follow-up if it proves useful.

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

## Future (post-1.0)

- **v1.1.0** — Per-project sharding (only if measured cross-project search latency justifies the refactor) + `agentvault tune` (calibrates `MIN_RELEVANCE` from injection-log evidence).
- Each future release continues to follow the principles below: one feature, fail open, hooks under ~150 tokens, every feature reversible via config, no co-author line in commits.

---

## Operating principles

- **One feature per release.** Multiple features only if they're tightly coupled (e.g., session-start + time-decay).
- **Fail open.** Hooks must never block Claude Code. Any error → exit 0, no output.
- **Token budget.** Every hook output stays under ~150 tokens unless the user opts in.
- **Reversible.** Every feature has a config flag to disable.
- **No co-author line in commits.**
