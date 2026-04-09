"""Obsidian vault writer — creates browsable markdown from sessions."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from agentvault.core.schema import AgentSession


def _format_frontmatter(session: AgentSession) -> str:
  """Generate YAML frontmatter for Obsidian."""
  lines = [
    "---",
    f"source: {session.source}",
    f"project: {session.project}",
    f"date: {session.started_at[:10] if session.started_at else 'unknown'}",
    f"session_id: {session.id}",
  ]
  if session.git_branch:
    lines.append(f"branch: {session.git_branch}")
  if session.tags:
    lines.append(f"tags: [{', '.join(session.tags)}]")
  if session.files_touched:
    lines.append(f"files_touched: {len(session.files_touched)}")
  lines.append("---")
  return "\n".join(lines)


def _format_exchange_markdown(session: AgentSession) -> str:
  """Format exchanges as readable markdown."""
  parts = []
  for ex in session.exchanges:
    if ex.role == "human":
      parts.append(f"### You\n{ex.content}")
    elif ex.role == "assistant":
      # Truncate very long assistant responses for readability
      content = ex.content
      if len(content) > 2000:
        content = content[:2000] + "\n\n*[truncated — full content in ChromaDB]*"

      tool_note = ""
      if ex.tool_calls:
        tools = ", ".join(tc.name for tc in ex.tool_calls)
        tool_note = f"\n> Tools: {tools}"

      parts.append(f"### Assistant{tool_note}\n{content}")

  return "\n\n---\n\n".join(parts)


def write_session(
  session: AgentSession,
  vault_path: Path,
) -> Path:
  """Write a single session to the Obsidian vault.

  Creates: vault_path/agent-history/{project}/{date}-{session_id[:8]}.md
  Returns the path to the created file.
  """
  date_str = session.started_at[:10] if session.started_at else "unknown"
  session_short = session.id[:8]

  # Create directory structure
  project_dir = vault_path / "agent-history" / session.project
  project_dir.mkdir(parents=True, exist_ok=True)

  filename = f"{date_str}-{session_short}.md"
  filepath = project_dir / filename

  # Build markdown content
  frontmatter = _format_frontmatter(session)

  header = f"# {session.source} — {session.project}"
  if session.git_branch:
    header += f" ({session.git_branch})"
  header += f"\n*{session.started_at} → {session.ended_at}*"

  summary_section = ""
  if session.summary:
    summary_section = f"\n## Summary\n{session.summary}\n"

  files_section = ""
  if session.files_touched:
    files_list = "\n".join(f"- `{f}`" for f in session.files_touched[:20])
    if len(session.files_touched) > 20:
      files_list += f"\n- *...and {len(session.files_touched) - 20} more*"
    files_section = f"\n## Files Touched\n{files_list}\n"

  transcript = _format_exchange_markdown(session)

  content = "\n\n".join(filter(None, [
    frontmatter,
    header,
    summary_section,
    files_section,
    "## Transcript",
    transcript,
  ]))

  filepath.write_text(content, encoding="utf-8")
  return filepath


def write_daily_digest(
  sessions: list[AgentSession],
  vault_path: Path,
  date: Optional[str] = None,
) -> Path:
  """Write a daily digest linking all sessions from a given date."""
  date_str = date or datetime.now().strftime("%Y-%m-%d")

  digest_dir = vault_path / "agent-history"
  digest_dir.mkdir(parents=True, exist_ok=True)
  filepath = digest_dir / f"{date_str}.md"

  lines = [
    "---",
    f"date: {date_str}",
    "type: daily-digest",
    "---",
    "",
    f"# Agent Sessions — {date_str}",
    "",
  ]

  for session in sessions:
    session_short = session.id[:8]
    exchange_count = len([e for e in session.exchanges if e.role == "human"])
    link = f"[[{session.project}/{date_str}-{session_short}|{session.source}: {session.project}]]"

    lines.append(f"- {link} — {exchange_count} exchanges")
    if session.git_branch:
      lines.append(f"  - Branch: `{session.git_branch}`")
    if session.summary:
      lines.append(f"  - {session.summary}")

  filepath.write_text("\n".join(lines), encoding="utf-8")
  return filepath
