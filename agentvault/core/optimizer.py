"""Token optimization for search results — reduce tokens without losing meaning."""

from __future__ import annotations

import re


def strip_tool_noise(text: str) -> str:
  """Remove tool call artifacts that waste tokens.

  Strips lines like:
    [Used tools: Read, Edit, Write]
    [Tools used: Read]
    **Assistant**: [Used tools: Bash]
  """
  lines = text.split("\n")
  cleaned = []
  for line in lines:
    stripped = line.strip()
    # Skip tool-only lines
    if re.match(r"^\[(?:Used )?[Tt]ools?(?: used)?:", stripped):
      continue
    if re.match(r"^\*\*Assistant\*\*: \[Used tools:", stripped):
      continue
    # Skip empty tool references
    if stripped in ("[Tools used: ]", "[Used tools: ]"):
      continue
    cleaned.append(line)
  return "\n".join(cleaned)


def truncate_code_blocks(text: str, max_lines: int = 4) -> str:
  """Truncate long code blocks to first N lines + indicator."""
  result = []
  in_code = False
  code_lines = 0
  code_truncated = False

  for line in text.split("\n"):
    if line.strip().startswith("```"):
      if not in_code:
        in_code = True
        code_lines = 0
        code_truncated = False
        result.append(line)
      else:
        in_code = False
        if code_truncated:
          result.append("  ... (truncated)")
        result.append(line)
      continue

    if in_code:
      code_lines += 1
      if code_lines <= max_lines:
        result.append(line)
      elif not code_truncated:
        code_truncated = True
    else:
      result.append(line)

  return "\n".join(result)


def dedup_results(results: list[dict], similarity_threshold: int = 100) -> list[dict]:
  """Remove near-duplicate results based on content prefix overlap."""
  seen_prefixes: set[str] = set()
  unique = []

  for hit in results:
    content = hit.get("content", "")
    # Normalize: lowercase, strip whitespace, take first N chars
    prefix = re.sub(r"\s+", " ", content.lower().strip())[:similarity_threshold]

    if prefix in seen_prefixes:
      continue
    seen_prefixes.add(prefix)
    unique.append(hit)

  return unique


def compact_metadata(meta: dict) -> str:
  """Format metadata as a single compact line."""
  project = meta.get("project", "?")
  source = meta.get("source", "?")
  branch = meta.get("git_branch", "")
  date = meta.get("timestamp", "?")[:10]

  parts = [project, source, date]
  if branch:
    parts.insert(2, branch)
  return " | ".join(parts)


def optimize_content(content: str) -> str:
  """Apply all content optimizations."""
  content = strip_tool_noise(content)
  content = truncate_code_blocks(content)
  # Remove excessive blank lines
  content = re.sub(r"\n{3,}", "\n\n", content)
  return content.strip()
