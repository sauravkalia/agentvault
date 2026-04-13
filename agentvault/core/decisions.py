"""Decision extraction from conversation content."""

from __future__ import annotations

import re
from dataclasses import dataclass

from agentvault.core.schema import AgentSession

# Patterns that indicate a decision was made
DECISION_PATTERNS = [
  re.compile(r"(?i)\b(?:decided|deciding)\s+(?:to|on|that)\b"),
  re.compile(r"(?i)\b(?:we'll|we will|i'll|i will)\s+(?:use|go with|switch)\b"),
  re.compile(r"(?i)\b(?:going|went)\s+with\b"),
  re.compile(r"(?i)\b(?:chose|chosen|choose)\b.*\bover\b"),
  re.compile(r"(?i)\bthe plan is\b"),
  re.compile(r"(?i)\bagreed on\b"),
  re.compile(r"(?i)\bswitching to\b"),
  re.compile(r"(?i)\blet'?s go with\b"),
  re.compile(r"(?i)\bwill use\b"),
  re.compile(r"(?i)\brecommend(?:ed|ing)?\s+(?:using|going with)\b"),
  re.compile(r"(?i)\bpicked\b.*\b(?:over|instead)\b"),
  re.compile(r"(?i)\bmigrat(?:e|ing|ed)\s+(?:to|from)\b"),
  re.compile(r"(?i)\breplac(?:e|ing|ed)\b.*\bwith\b"),
]


@dataclass
class Decision:
  """A decision extracted from a conversation."""

  text: str
  session_id: str
  project: str
  timestamp: str
  source: str


def _extract_sentence(text: str, match_start: int) -> str:
  """Extract the sentence containing the match position."""
  # Find sentence boundaries
  before = text[:match_start].rfind(". ")
  if before == -1:
    before = 0
  else:
    before += 2

  after = text.find(". ", match_start)
  if after == -1:
    after = len(text)
  else:
    after += 1

  sentence = text[before:after].strip()
  # Cap length
  if len(sentence) > 300:
    sentence = sentence[:300] + "..."
  return sentence


def extract_decisions(session: AgentSession) -> list[Decision]:
  """Extract decisions from a session's conversation content."""
  decisions: list[Decision] = []
  seen_texts: set[str] = set()

  for exchange in session.exchanges:
    if not exchange.content:
      continue

    for pattern in DECISION_PATTERNS:
      for match in pattern.finditer(exchange.content):
        sentence = _extract_sentence(exchange.content, match.start())
        if not sentence:
          continue

        # Deduplicate similar decisions
        normalized = sentence.lower()[:100]
        if normalized in seen_texts:
          continue
        seen_texts.add(normalized)

        decisions.append(Decision(
          text=sentence,
          session_id=session.id,
          project=session.project,
          timestamp=exchange.timestamp or session.started_at,
          source=session.source,
        ))

  return decisions


def format_decisions_markdown(decisions: list[Decision]) -> str:
  """Format decisions as markdown."""
  if not decisions:
    return ""

  lines = []
  for d in decisions:
    date = d.timestamp[:10] if d.timestamp else "?"
    lines.append(
      f"- **{d.project}** ({d.source}, {date}): {d.text}"
    )
  return "\n".join(lines)
