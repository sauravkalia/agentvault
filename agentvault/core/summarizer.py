"""Session summary generator using keyword extraction."""

from __future__ import annotations

import re
from collections import Counter

from agentvault.core.schema import AgentSession

# Common stopwords to filter out
STOPWORDS = frozenset({
  "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
  "have", "has", "had", "do", "does", "did", "will", "would", "could",
  "should", "may", "might", "shall", "can", "need", "dare", "ought",
  "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
  "as", "into", "through", "during", "before", "after", "above", "below",
  "between", "out", "off", "over", "under", "again", "further", "then",
  "once", "here", "there", "when", "where", "why", "how", "all", "both",
  "each", "few", "more", "most", "other", "some", "such", "no", "nor",
  "not", "only", "own", "same", "so", "than", "too", "very", "just",
  "don", "now", "and", "but", "or", "if", "while", "about", "up",
  "this", "that", "these", "those", "it", "its", "i", "me", "my",
  "we", "our", "you", "your", "he", "him", "his", "she", "her",
  "they", "them", "their", "what", "which", "who", "whom", "let",
  "also", "like", "get", "got", "use", "using", "make", "one", "two",
  "yes", "ok", "okay", "sure", "right", "well", "think", "know",
  "see", "look", "want", "going", "thing", "way", "file", "code",
  "run", "set", "add", "new", "try", "check", "please", "thanks",
})

# Minimum word length to consider
MIN_WORD_LENGTH = 3


def _extract_keywords(text: str, top_n: int = 5) -> list[str]:
  """Extract top keywords from text using word frequency."""
  words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text.lower())
  filtered = [w for w in words if w not in STOPWORDS and len(w) >= MIN_WORD_LENGTH]
  counts = Counter(filtered)
  return [word for word, _ in counts.most_common(top_n)]


def generate_summary(session: AgentSession) -> str:
  """Generate a concise summary for a session.

  Uses keyword extraction (no LLM needed) to identify
  main topics, plus counts of exchanges, tools, and files.
  """
  if not session.exchanges:
    return "Empty session."

  # Count exchanges by role
  human_count = sum(1 for e in session.exchanges if e.role == "human")
  assistant_count = sum(1 for e in session.exchanges if e.role == "assistant")

  # Collect all tool names used
  tools_used: set[str] = set()
  for ex in session.exchanges:
    for tc in ex.tool_calls:
      tools_used.add(tc.name)

  # Extract keywords from human messages (what the user asked about)
  human_text = " ".join(
    e.content for e in session.exchanges if e.role == "human"
  )
  keywords = _extract_keywords(human_text)

  # Build summary parts
  parts = []

  # Exchange count
  parts.append(f"{human_count + assistant_count} exchanges")

  # Topics
  if keywords:
    parts.append(f"about {', '.join(keywords[:4])}")

  # Tools
  if tools_used:
    parts.append(f"Tools: {', '.join(sorted(tools_used)[:5])}")

  # Files
  if session.files_touched:
    parts.append(f"{len(session.files_touched)} files modified")

  return ". ".join(parts) + "."
