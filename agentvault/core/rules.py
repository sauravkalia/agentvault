"""Detect correction-style rules repeated across past AI sessions.

Walks chunks for phrases that look like the user telling the assistant
how to behave ("don't X", "always X", "use X instead of Y", "stop doing
X"). Clusters similar corrections by Jaccard overlap on content tokens
and surfaces any cluster repeated across N+ distinct sessions as a
candidate rule worth promoting to CLAUDE.md.

Heuristic and noisy — companion command to `agentvault patterns` /
`agentvault todos`. The user picks which candidates are worth lifting
into a persistent rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

# Each pattern captures the corrective directive in group 1. Tuned for
# recall; clustering + the min-occurrences threshold trim noise.
_RULE_PATTERNS = [
  re.compile(r"(?i)\b(?:please\s+)?don['’]t\s+(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\b(?:please\s+)?do not\s+(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\bnever\s+(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\balways\s+(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\bstop\s+(?:doing\s+|using\s+)?(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\buse\s+(.+?)\s+(?:instead|rather than|not)\b(.+?)?(?:[.!?]|$)"),
  re.compile(r"(?i)\bprefer\s+(.+?)\s+over\b"),
  re.compile(r"(?i)\bavoid\s+(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\bi (?:already\s+)?(?:told|asked|said) you\s+(?:to\s+|not to\s+)?(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\bremember\s+to\s+(.+?)(?:[.!?]|$)"),
  re.compile(r"(?i)\bmake sure (?:to\s+|you\s+|that\s+)?(.+?)(?:[.!?]|$)"),
]

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")
_MIN_WORD_LEN = 3
_MIN_TOKENS = 2
_MAX_TEXT_LEN = 180
# Threshold tuned slightly lower than patterns.py — corrective phrasings
# tend to have more verb-conjugation noise ("add" vs "adding" vs "added")
# that suppresses overlap.
_JACCARD = 0.4

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
}


@dataclass
class RuleCandidate:
  example: str
  tokens: set[str]
  session_ids: set[str] = field(default_factory=set)
  projects: set[str] = field(default_factory=set)
  sources: set[str] = field(default_factory=set)
  first_seen: str = ""
  last_seen: str = ""
  examples: list[str] = field(default_factory=list)

  @property
  def occurrence_count(self) -> int:
    return len(self.session_ids)


def _content_tokens(text: str) -> frozenset[str]:
  toks = (t.lower() for t in _WORD_RE.findall(text))
  return frozenset(
    t for t in toks if t not in _STOPWORDS and len(t) >= _MIN_WORD_LEN
  )


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
  if not a or not b:
    return 0.0
  inter = len(a & b)
  if inter == 0:
    return 0.0
  return inter / len(a | b)


def _extract_directives(content: str):
  """Yield (display_text, token_set) for each correction-flavor match."""
  if not content:
    return
  seen_in_chunk: list[frozenset[str]] = []
  for pattern in _RULE_PATTERNS:
    for m in pattern.finditer(content):
      body = " ".join(g for g in m.groups() if g).strip()
      if not body:
        continue
      if len(body) > _MAX_TEXT_LEN:
        body = body[:_MAX_TEXT_LEN].rstrip() + "…"
      tokens = _content_tokens(body)
      if len(tokens) < _MIN_TOKENS:
        continue
      # Dedupe near-identical matches within one chunk.
      if any(_jaccard(tokens, prev) >= 0.7 for prev in seen_in_chunk):
        continue
      seen_in_chunk.append(tokens)
      # Reconstruct a readable directive: prepend the trigger verb when
      # the regex captured everything after it.
      trigger = (m.group(0).split(body, 1)[0] or "").strip().rstrip(":")
      display = f"{trigger} {body}".strip() if trigger else body
      yield display, tokens


def find_rules(
  store: Any,
  *,
  project: Optional[str] = None,
  min_occurrences: int = 3,
  top_n: int = 20,
  chunk_limit: int = 5000,
) -> list[RuleCandidate]:
  """Walk the vault and surface repeated correction-style directives.

  Args:
    project: limit to a single project.
    min_occurrences: require this many distinct sessions per cluster.
    top_n: cap on returned clusters (sorted by occurrence count desc,
      ties broken by most-recent).
    chunk_limit: cap on chunks pulled from the vault.
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

  clusters: list[tuple[set[str], RuleCandidate]] = []

  for i, _cid in enumerate(ids):
    content = docs[i] if i < len(docs) else ""
    meta = metas[i] if i < len(metas) else {}
    session_id = meta.get("session_id") or ""
    proj = meta.get("project") or ""
    src = meta.get("source") or ""
    ts = meta.get("timestamp") or ""

    seen_in_chunk: list[frozenset[str]] = []
    for display, tokens in _extract_directives(content):
      if any(_jaccard(tokens, prev) >= _JACCARD for prev in seen_in_chunk):
        continue
      seen_in_chunk.append(tokens)

      target: Optional[RuleCandidate] = None
      target_center: Optional[set[str]] = None
      best = 0.0
      for center, cand in clusters:
        sim = _jaccard(tokens, frozenset(center))
        if sim >= _JACCARD and sim > best:
          best = sim
          target = cand
          target_center = center

      if target is None:
        cand = RuleCandidate(example=display, tokens=set(tokens))
        target_center = set(tokens)
        clusters.append((target_center, cand))
        target = cand
        target.examples.append(display)
      else:
        assert target_center is not None
        target_center |= tokens
        target.tokens = target_center
        if display not in target.examples and len(target.examples) < 5:
          target.examples.append(display)

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

  qualified = [c for _, c in clusters if c.occurrence_count >= min_occurrences]
  qualified.sort(key=lambda c: c.last_seen, reverse=True)
  qualified.sort(key=lambda c: c.occurrence_count, reverse=True)
  return qualified[:top_n]


def format_rules_text(candidates: list[RuleCandidate]) -> str:
  if not candidates:
    return "No repeated correction patterns found above the threshold."
  lines = [f"Found {len(candidates)} candidate rules:\n"]
  for c in candidates:
    first = (c.first_seen or "")[:10]
    last = (c.last_seen or "")[:10]
    span = (
      f"{first} → {last}" if first and last and first != last
      else (last or first or "?")
    )
    projs = ", ".join(sorted(c.projects)) or "?"
    lines.append(
      f"- [{c.occurrence_count} sessions, {span}, {projs}] {c.example}"
    )
  return "\n".join(lines)
