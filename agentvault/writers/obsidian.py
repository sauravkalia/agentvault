"""Obsidian vault writer — creates browsable markdown from sessions."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from agentvault.core.decisions import extract_decisions
from agentvault.core.redactor import redact_secrets
from agentvault.core.schema import AgentSession


def _relativize_path(file_path: str, working_dir: str) -> str:
  """Make absolute path relative to working directory for display."""
  if working_dir and file_path.startswith(working_dir):
    rel = file_path[len(working_dir):].lstrip("/")
    return rel or file_path
  # Fallback: just show filename
  return Path(file_path).name


def _sanitize_path_component(name: str) -> str:
  """Remove path separators, null bytes, and '..' from a path component."""
  return re.sub(r'[^\w\-.]', '_', name).strip('.')


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
      parts.append(f"### You\n{redact_secrets(ex.content)}")
    elif ex.role == "assistant":
      # Truncate very long assistant responses for readability
      content = redact_secrets(ex.content)
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
  safe_project = _sanitize_path_component(session.project)
  safe_session = _sanitize_path_component(session.id[:8])

  # Create directory structure
  project_dir = vault_path / "agent-history" / safe_project
  project_dir.mkdir(parents=True, exist_ok=True)

  filename = f"{date_str}-{safe_session}.md"
  filepath = project_dir / filename

  # Ensure resolved path is still under the vault (prevent traversal)
  if not filepath.resolve().is_relative_to(vault_path.resolve()):
    raise ValueError(f"Path traversal detected: {filepath}")

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
    rel_files = [_relativize_path(f, session.working_directory) for f in session.files_touched[:20]]
    files_list = "\n".join(f"- `{f}`" for f in rel_files)
    if len(session.files_touched) > 20:
      files_list += f"\n- *...and {len(session.files_touched) - 20} more*"
    files_section = f"\n## Files Touched\n{files_list}\n"

  decisions_section = ""
  decisions = extract_decisions(session)
  if decisions:
    dec_lines = "\n".join(f"- {d.text}" for d in decisions[:10])
    decisions_section = f"\n## Key Decisions\n{dec_lines}\n"

  transcript = _format_exchange_markdown(session)

  content = "\n\n".join(filter(None, [
    frontmatter,
    header,
    summary_section,
    decisions_section,
    files_section,
    "## Transcript",
    transcript,
  ]))

  # Write with restrictive permissions (owner-only read/write)
  fd = os.open(str(filepath), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
  try:
    os.write(fd, content.encode("utf-8"))
  finally:
    os.close(fd)
  return filepath


def write_daily_digest(
  sessions: list[AgentSession],
  vault_path: Path,
  date: Optional[str] = None,
) -> Path:
  """Write a daily digest linking all sessions from a given date."""
  date_str = _sanitize_path_component(date or datetime.now().strftime("%Y-%m-%d"))

  digest_dir = vault_path / "agent-history"
  digest_dir.mkdir(parents=True, exist_ok=True)
  filepath = digest_dir / f"{date_str}.md"

  # Ensure resolved path is still under the vault (prevent traversal)
  if not filepath.resolve().is_relative_to(vault_path.resolve()):
    raise ValueError(f"Path traversal detected: {filepath}")

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
    safe_project = _sanitize_path_component(session.project)
    safe_session = _sanitize_path_component(session.id[:8])
    exchange_count = len([e for e in session.exchanges if e.role == "human"])
    link = f"[[{safe_project}/{date_str}-{safe_session}|{session.source}: {safe_project}]]"

    lines.append(f"- {link} — {exchange_count} exchanges")
    if session.git_branch:
      lines.append(f"  - Branch: `{session.git_branch}`")
    if session.summary:
      lines.append(f"  - {session.summary}")

  # Write with restrictive permissions (owner-only read/write)
  fd = os.open(str(filepath), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
  try:
    os.write(fd, "\n".join(lines).encode("utf-8"))
  finally:
    os.close(fd)
  return filepath
