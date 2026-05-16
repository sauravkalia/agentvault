"""Recurring-problem detection across past AI sessions.

Walks chunks, pulls out problem-flavor lines (errors, failures, "doesn't
work" reports), reduces each to a small bag-of-content-words fingerprint,
and clusters by fingerprint. Any cluster spanning ≥ `min_sessions`
distinct sessions is surfaced as a recurring problem worth flagging.

This is deliberately heuristic — fast, no ML, no extra dependencies. The
point is to say "you've debugged this kind of thing N times" not to
classify the exact bug.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

# Lines containing any of these markers are considered "problem-flavor"
# and become candidate signals. Tuned for high recall — we de-noise
# later via the fingerprint + session-count threshold.
_PROBLEM_PATTERNS = [
  # `error` matches without word boundaries so stack-trace tokens like
  # TypeError / ValueError / ReferenceError still count as a signal.
  re.compile(r"(?i)error"),
  re.compile(r"(?i)exception"),
  re.compile(r"(?i)traceback"),
  re.compile(r"(?i)\bbroken\b"),
  re.compile(r"(?i)\bdoes(?:n['’]t| not)\s+work\b"),
  re.compile(r"(?i)\bnot working\b"),
  re.compile(r"(?i)\bisn['’]t working\b"),
  re.compile(r"(?i)\bfail(?:s|ed|ing|ure)?\b"),
  re.compile(r"(?i)\bcrash(?:es|ed|ing)?\b"),
  re.compile(r"(?i)\b(?:un|not\s+)defined\b"),
  re.compile(r"(?i)\bnull\b"),
  re.compile(r"(?i)\bstack\s*trace\b"),
  re.compile(r"(?i)\bcan['’]t\b"),
  re.compile(r"(?i)\bcannot\b"),
  # `\bbug\b` keeps the boundaries so `debug` / `debugging` don't match.
  re.compile(r"(?i)\bbug\b"),
  re.compile(r"(?i)\bregression\b"),
  re.compile(r"(?i)\bhang(?:s|ing|ed)?\b"),
  re.compile(r"(?i)\btimeout\b"),
  re.compile(r"(?i)\b500\b|\b502\b|\b503\b|\b504\b"),
]

# Stopwords kept small on purpose — we want a *content* fingerprint, not
# stylistic. Adding too many tokens here makes fingerprints collide.
_STOPWORDS = {
  "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
  "and", "or", "but", "if", "then", "of", "to", "in", "on", "at", "by",
  "for", "with", "from", "as", "this", "that", "these", "those", "it",
  "its", "i", "you", "we", "they", "he", "she", "him", "her", "them",
  "my", "your", "our", "their", "his", "hers",
  "do", "does", "did", "doing", "done",
  "have", "has", "had", "having",
  "will", "would", "should", "could", "can", "may", "might", "must",
  "so", "than", "very", "just", "also", "too", "only", "still",
  "what", "when", "where", "why", "how", "which", "who",
  "not", "no", "yes",
  # Connectives that distort fingerprints when included.
  "because", "before", "after", "while", "during", "since", "until",
  "again", "still", "now", "later",
  # Common AI-chat filler we don't want dominating fingerprints.
  "please", "thanks", "ok", "okay", "great", "sure", "let",
  "like", "want", "need", "use", "using", "used",
  "going", "get", "got", "make", "makes", "making", "made",
  "see", "seems", "looks", "look",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")
_MIN_WORD_LEN = 3
_MIN_SIGNAL_TOKENS = 3  # lines with <3 content words are too generic
_MAX_LINE_LEN = 240
_JACCARD_THRESHOLD = 0.5  # token-set overlap required to merge clusters


@dataclass
class RecurringPattern:
  """A cluster of similar problem-flavor signals seen across sessions."""

  fingerprint: str
  example: str
  session_ids: set[str] = field(default_factory=set)
  projects: set[str] = field(default_factory=set)
  sources: set[str] = field(default_factory=set)
  first_seen: str = ""
  last_seen: str = ""
  chunk_ids: list[str] = field(default_factory=list)

  @property
  def session_count(self) -> int:
    return len(self.session_ids)


def _is_problem_line(line: str) -> bool:
  return any(p.search(line) for p in _PROBLEM_PATTERNS)


def _signature_tokens(line: str) -> Optional[frozenset[str]]:
  """Extract the content-token set used for similarity comparison.

  Returns None for lines too thin to fingerprint usefully.
  """
  tokens = [t.lower() for t in _WORD_RE.findall(line)]
  content = {
    t for t in tokens
    if t not in _STOPWORDS and len(t) >= _MIN_WORD_LEN
  }
  if len(content) < _MIN_SIGNAL_TOKENS:
    return None
  return frozenset(content)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
  if not a or not b:
    return 0.0
  inter = len(a & b)
  if inter == 0:
    return 0.0
  return inter / len(a | b)


def _fingerprint(line: str) -> Optional[str]:
  """Stable, human-readable rendering of a line's content vocabulary.

  Returns None if the line is too short on content to be a useful signal.
  Kept as a public-ish helper for tests and display formatting.
  """
  tokens = _signature_tokens(line)
  if tokens is None:
    return None
  return " ".join(sorted(tokens))


def _iter_problem_signals(content: str):
  """Yield (line_text, token_set) for each problem-flavor line."""
  for raw in content.splitlines():
    line = raw.strip()
    if not line or len(line) < 8:
      continue
    if len(line) > _MAX_LINE_LEN:
      line = line[:_MAX_LINE_LEN]
    if not _is_problem_line(line):
      continue
    tokens = _signature_tokens(line)
    if tokens:
      yield line, tokens


def find_patterns(
  store: Any,
  *,
  project: Optional[str] = None,
  min_sessions: int = 3,
  top_n: int = 20,
  chunk_limit: int = 5000,
) -> list[RecurringPattern]:
  """Scan the vault for recurring problem-flavor clusters.

  Args:
    store: VaultStore (or anything with a `collection.get` returning
      ``{ids, documents, metadatas}``).
    project: limit the scan to this project name.
    min_sessions: require this many distinct sessions per cluster.
    top_n: cap on returned clusters (sorted by session count, then by
      most-recent activity).
    chunk_limit: cap on chunks pulled from the vault (the scan is O(N)
      over content; this bounds the cost on large stores).
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

  # Greedy single-link clustering by Jaccard similarity over content
  # token sets. Each cluster keeps its growing union-set as the centroid
  # so a fingerprint that grows fuzzy still merges new signals fairly.
  clusters: list[tuple[set[str], RecurringPattern]] = []

  for i, cid in enumerate(ids):
    content = docs[i] if i < len(docs) else ""
    meta = metas[i] if i < len(metas) else {}
    session_id = meta.get("session_id") or ""
    proj = meta.get("project") or ""
    src = meta.get("source") or ""
    ts = meta.get("timestamp") or ""

    if not content:
      continue

    seen_in_chunk: list[frozenset[str]] = []
    for line, tokens in _iter_problem_signals(content):
      # Drop near-duplicates within the same chunk — a chunk that
      # mentions the same problem 5 times still counts as one
      # occurrence in that chunk's session.
      if any(_jaccard(tokens, prev) >= _JACCARD_THRESHOLD for prev in seen_in_chunk):
        continue
      seen_in_chunk.append(tokens)

      target: Optional[RecurringPattern] = None
      target_center: Optional[set[str]] = None
      best_sim = 0.0
      for center, cluster in clusters:
        sim = _jaccard(tokens, frozenset(center))
        if sim >= _JACCARD_THRESHOLD and sim > best_sim:
          best_sim = sim
          target = cluster
          target_center = center

      if target is None:
        cluster = RecurringPattern(
          fingerprint=" ".join(sorted(tokens)),
          example=line,
        )
        target_center = set(tokens)
        clusters.append((target_center, cluster))
        target = cluster
      else:
        # Grow the centroid by union so later signals can match through
        # vocabulary drift (e.g. one description mentions "redis", another
        # mentions "memcached" + the shared cluster vocabulary).
        assert target_center is not None
        target_center |= tokens
        target.fingerprint = " ".join(sorted(target_center))

      if session_id:
        target.session_ids.add(session_id)
      if proj:
        target.projects.add(proj)
      if src:
        target.sources.add(src)
      if ts:
        if not target.first_seen or ts < target.first_seen:
          target.first_seen = ts
        if ts > target.last_seen:
          target.last_seen = ts
      target.chunk_ids.append(cid)

  qualified = [c for _, c in clusters if c.session_count >= min_sessions]
  # Most-sessions first; ties broken by most-recently-active first.
  # ISO-8601 timestamps sort lexicographically, so we use two stable
  # sort passes: secondary first, then primary.
  qualified.sort(key=lambda c: c.last_seen, reverse=True)
  qualified.sort(key=lambda c: c.session_count, reverse=True)
  return qualified[:top_n]


def format_patterns_text(patterns: list[RecurringPattern]) -> str:
  """Plain-text rendering for the MCP tool / CLI fallback."""
  if not patterns:
    return "No recurring problems found above the threshold."

  lines = [f"Found {len(patterns)} recurring problems:\n"]
  for p in patterns:
    first = (p.first_seen or "")[:10]
    last = (p.last_seen or "")[:10]
    span = f"{first} → {last}" if first and last and first != last else (last or first or "?")
    projs = ", ".join(sorted(p.projects)) or "?"
    lines.append(
      f"- [{p.session_count} sessions, {span}, {projs}] {p.example}"
    )
    lines.append(f"    fingerprint: {p.fingerprint}")
  return "\n".join(lines)
