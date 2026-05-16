"""Stale-TODO extraction from past AI session content.

Walks chunks, pulls out TODO-flavor phrases ("we should X", "TODO:", "I'll
come back to X", "would be nice to X"), and marks each as resolved when a
later chunk in the same project contains a "done"-flavor line whose
content-token set overlaps the TODO's tokens by Jaccard ≥ 0.4.

Heuristic and noisy by design — the point is to surface what the user
half-promised themselves and never circled back to, not to be perfect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

# Each pattern captures the TODO body in group 1. Tuned for high recall;
# the resolution heuristic and the user filtering by --unresolved both
# trim noise downstream.
_TODO_PATTERNS = [
  re.compile(r"(?i)\bTODO[:\s]+(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\bFIXME[:\s]+(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\bXXX[:\s]+(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\b(?:we|i)\s+should\s+(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\b(?:we|i)(?:'ll| will)\s+(?:come back to|revisit|circle back to)\s+(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\b(?:let['’]?s|let us)\s+(?:add|fix|implement|do|tackle|handle)\s+(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\b(?:need(?:s)?\s+to|needs?\s+to\s+be)\s+(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\bwould be (?:nice|good|great) to\s+(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\b(?:gonna|going to)\s+(?:add|fix|implement|tackle|handle)\s+(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\b(?:add|fix|implement)\s+(.+?)\s+later\b"),
]

# Verbs that signal a TODO was carried out in a later message.
_DONE_PATTERN = re.compile(
  r"(?i)\b(?:added|fixed|shipped|completed|done|implemented|landed|merged|"
  r"finished|resolved|wrapped\s+up|took\s+care\s+of)\b"
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")
_MIN_WORD_LEN = 3
_MIN_TOKENS = 2  # need at least 2 content words to bother
_MAX_TEXT_LEN = 200
_RESOLUTION_JACCARD = 0.4

# Reuse the stopword set conceptually — kept inline so this module isn't
# coupled to patterns.py beyond what they happen to share.
_STOPWORDS = {
  "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
  "and", "or", "but", "if", "then", "of", "to", "in", "on", "at", "by",
  "for", "with", "from", "as", "this", "that", "these", "those", "it",
  "its", "i", "you", "we", "they",
  "do", "does", "did", "doing", "done",
  "have", "has", "had", "having",
  "will", "would", "should", "could", "can",
  "so", "than", "very", "just", "also", "too", "only", "still",
  "what", "when", "where", "why", "how", "which",
  "not", "no", "yes",
  "please", "thanks", "ok", "okay", "sure", "let",
  "like", "want", "need", "use", "using", "used",
  "going", "get", "got", "make", "makes", "making", "made",
  "add", "fix", "implement",  # the trigger verbs themselves
}


@dataclass
class Todo:
  text: str
  tokens: frozenset[str]
  session_id: str
  project: str
  source: str
  timestamp: str
  chunk_id: str
  resolved: bool = False
  resolved_by_chunk: str = ""
  resolved_at: str = ""

  @property
  def date(self) -> str:
    return (self.timestamp or "")[:10]


def _content_tokens(text: str) -> frozenset[str]:
  toks = (t.lower() for t in _WORD_RE.findall(text))
  return frozenset(
    t for t in toks if t not in _STOPWORDS and len(t) >= _MIN_WORD_LEN
  )


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
  if not a or not b:
    return 0.0
  inter = len(a & b)
  if not inter:
    return 0.0
  return inter / len(a | b)


@dataclass
class _ChunkRecord:
  """Internal: everything we need to scan one chunk in two passes."""
  cid: str
  content: str
  session_id: str
  project: str
  source: str
  timestamp: str


def _iter_todos_in_chunk(rec: _ChunkRecord):
  """Yield Todo objects extracted from one chunk's content."""
  if not rec.content:
    return
  seen_tokens: list[frozenset[str]] = []
  for pattern in _TODO_PATTERNS:
    for m in pattern.finditer(rec.content):
      body = m.group(1).strip()
      if not body:
        continue
      if len(body) > _MAX_TEXT_LEN:
        body = body[:_MAX_TEXT_LEN].rstrip() + "…"
      tokens = _content_tokens(body)
      if len(tokens) < _MIN_TOKENS:
        continue
      # Dedupe near-identical TODOs inside one chunk so the same line
      # matched by two patterns doesn't double-count.
      if any(_jaccard(tokens, prev) >= 0.7 for prev in seen_tokens):
        continue
      seen_tokens.append(tokens)

      # Build the displayed text. Trim leading filler/connectives the
      # capture group sometimes pulls in.
      text = re.sub(r"^[\s,;:-]+", "", body).strip()
      yield Todo(
        text=text,
        tokens=tokens,
        session_id=rec.session_id,
        project=rec.project,
        source=rec.source,
        timestamp=rec.timestamp,
        chunk_id=rec.cid,
      )


def _done_signals_in_chunk(rec: _ChunkRecord):
  """Yield (line_tokens, line_text) for each done-flavor line in the chunk."""
  if not rec.content:
    return
  for raw in rec.content.splitlines():
    line = raw.strip()
    if not line or len(line) < 8:
      continue
    if not _DONE_PATTERN.search(line):
      continue
    tokens = _content_tokens(line)
    if tokens:
      yield tokens, line


def find_todos(
  store: Any,
  *,
  project: Optional[str] = None,
  only_unresolved: bool = False,
  top_n: int = 50,
  chunk_limit: int = 5000,
) -> list[Todo]:
  """Walk the vault for TODO-flavor phrases, attach resolution status.

  Two-pass over the chunks sorted by timestamp ascending:
    1. Extract every TODO into a flat list.
    2. For each TODO, scan only the chunks that arrived *after* it in
       the same project for a done-flavor line whose tokens overlap
       (Jaccard ≥ 0.4). First match wins.
  """
  where = {"project": project} if project else None
  try:
    page = store.collection.get(
      limit=chunk_limit,
      include=["documents", "metadatas"],
      where=where,
    )
  except Exception:
    return []

  ids = page.get("ids", []) or []
  docs = page.get("documents", []) or []
  metas = page.get("metadatas", []) or []

  records: list[_ChunkRecord] = []
  for i, cid in enumerate(ids):
    meta = metas[i] if i < len(metas) else {}
    records.append(_ChunkRecord(
      cid=cid,
      content=docs[i] if i < len(docs) else "",
      session_id=meta.get("session_id") or "",
      project=meta.get("project") or "",
      source=meta.get("source") or "",
      timestamp=meta.get("timestamp") or "",
    ))

  # Sort ascending so "later chunks" really are later by wall clock.
  records.sort(key=lambda r: r.timestamp)

  # Pass 1 — extract.
  todos: list[Todo] = []
  for rec in records:
    todos.extend(_iter_todos_in_chunk(rec))

  if not todos:
    return []

  # Pre-compute done signals per chunk for the resolution pass so we
  # don't re-tokenize every chunk for every TODO.
  done_by_chunk: list[tuple[_ChunkRecord, list[tuple[frozenset[str], str]]]] = []
  for rec in records:
    signals = list(_done_signals_in_chunk(rec))
    if signals:
      done_by_chunk.append((rec, signals))

  # Pass 2 — resolve.
  for todo in todos:
    for rec, signals in done_by_chunk:
      # Only later, same-project chunks count as resolution.
      if rec.timestamp <= todo.timestamp:
        continue
      if rec.project != todo.project:
        continue
      for tokens, line in signals:
        if _jaccard(todo.tokens, tokens) >= _RESOLUTION_JACCARD:
          todo.resolved = True
          todo.resolved_by_chunk = rec.cid
          todo.resolved_at = rec.timestamp
          break
      if todo.resolved:
        break

  if only_unresolved:
    todos = [t for t in todos if not t.resolved]

  # Newest TODO first — that's the most actionable order when you're
  # reading the list, especially with --unresolved.
  todos.sort(key=lambda t: t.timestamp, reverse=True)
  return todos[:top_n]


def format_todos_text(todos: list[Todo]) -> str:
  if not todos:
    return "No TODOs found."
  open_n = sum(1 for t in todos if not t.resolved)
  done_n = len(todos) - open_n
  lines = [f"Found {len(todos)} TODOs ({open_n} open, {done_n} resolved):\n"]
  for t in todos:
    badge = "done" if t.resolved else "open"
    lines.append(
      f"- [{badge}] [{t.project} · {t.source} · {t.date}] {t.text}"
    )
    if t.resolved and t.resolved_at:
      lines.append(f"    resolved {t.resolved_at[:10]} ({t.resolved_by_chunk})")
  return "\n".join(lines)
