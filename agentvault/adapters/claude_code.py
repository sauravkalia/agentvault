"""Adapter for Claude Code conversation history.

Claude Code stores conversations as JSONL files at:
  ~/.claude/projects/{project-slug}/{session-id}.jsonl

Each line is a JSON object with a "type" field:
  - "user"       — user messages
  - "assistant"  — AI responses (text + tool_use blocks)
  - "system"     — system prompts
  - "attachment"  — MCP tools, skills
  - "file-history-snapshot" — file state tracking
  - "permission-mode" — session config

Key metadata per message:
  - cwd: working directory (identifies project)
  - gitBranch: current git branch
  - sessionId: groups conversation
  - timestamp: ISO 8601
  - parentUuid: message threading
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentvault.adapters.base import BaseAdapter
from agentvault.core.schema import AgentSession, Exchange, ToolCall


def _extract_project_name(cwd: str) -> str:
  """Extract project name from working directory path."""
  return Path(cwd).name if cwd else "unknown"


def _extract_project_from_slug(slug: str) -> str:
  """Extract project name from Claude Code's directory slug.

  Slug format: -Users-Name-Documents-GitHub-project-name
  """
  parts = slug.split("-")
  # Find the last meaningful segment(s) after common path components
  skip = {"Users", "Documents", "GitHub", "Projects", "Code", "Home", "home", "src"}
  meaningful = [p for p in parts if p and p not in skip]
  if meaningful:
    return meaningful[-1]
  return slug


def _extract_text_content(content: Any) -> str:
  """Extract text from message content (string or block list)."""
  if isinstance(content, str):
    return content

  if isinstance(content, list):
    texts = []
    for block in content:
      if isinstance(block, dict) and block.get("type") == "text":
        texts.append(block.get("text", ""))
    return "\n".join(texts)

  return str(content)


def _extract_tool_calls(content: Any) -> list[ToolCall]:
  """Extract tool calls from assistant message content blocks."""
  if not isinstance(content, list):
    return []

  calls = []
  for block in content:
    if isinstance(block, dict) and block.get("type") == "tool_use":
      calls.append(ToolCall(
        name=block.get("name", "unknown"),
        input=block.get("input", {}),
      ))
  return calls


class ClaudeCodeAdapter(BaseAdapter):
  name = "claude-code"
  description = "Claude Code CLI conversation history"

  def default_history_path(self) -> Path:
    return Path.home() / ".claude" / "projects"

  def detect(self) -> bool:
    return self.history_path.exists() and any(self.history_path.iterdir())

  def discover_sessions(self) -> list[Path]:
    """Find all .jsonl session files across all projects."""
    if not self.history_path.exists():
      return []

    sessions = []
    for project_dir in self.history_path.iterdir():
      if not project_dir.is_dir():
        continue
      for jsonl_file in sorted(project_dir.glob("*.jsonl")):
        # Skip subagent files
        if "subagents" in str(jsonl_file):
          continue
        sessions.append(jsonl_file)

    return sorted(sessions, key=lambda p: p.stat().st_mtime)

  def parse_session(self, path: Path) -> AgentSession | None:
    """Parse a Claude Code JSONL session file into AgentSession."""
    lines = path.read_text(encoding="utf-8", errors="replace").strip().split("\n")
    if not lines:
      return None

    exchanges: list[Exchange] = []
    session_id = ""
    cwd = ""
    git_branch = ""
    first_timestamp = ""
    last_timestamp = ""
    files_touched: set[str] = set()

    for line in lines:
      try:
        obj = json.loads(line)
      except json.JSONDecodeError:
        continue

      msg_type = obj.get("type", "")
      timestamp = obj.get("timestamp", "")

      # Track timestamps
      if timestamp:
        if not first_timestamp:
          first_timestamp = timestamp
        last_timestamp = timestamp

      # Extract session metadata from first message with it
      if not session_id and obj.get("sessionId"):
        session_id = obj["sessionId"]
      if not cwd and obj.get("cwd"):
        cwd = obj["cwd"]
      if not git_branch and obj.get("gitBranch"):
        git_branch = obj["gitBranch"]

      # Parse user messages
      if msg_type == "user":
        message = obj.get("message", {})
        content = message.get("content", "")
        text = _extract_text_content(content)
        if text.strip():
          exchanges.append(Exchange(
            role="human",
            content=text.strip(),
            timestamp=timestamp,
          ))

      # Parse assistant messages
      elif msg_type == "assistant":
        message = obj.get("message", {})
        content = message.get("content", "")
        text = _extract_text_content(content)
        tool_calls = _extract_tool_calls(message.get("content", []))

        # Track files touched by tool calls
        for tc in tool_calls:
          if tc.name in ("Read", "Edit", "Write") and "file_path" in tc.input:
            files_touched.add(tc.input["file_path"])

        if text.strip() or tool_calls:
          if text.strip():
            msg_content = text.strip()
          else:
            tool_names = ", ".join(tc.name for tc in tool_calls)
            msg_content = f"[Used tools: {tool_names}]"
          exchanges.append(Exchange(
            role="assistant",
            content=msg_content,
            timestamp=timestamp,
            tool_calls=tool_calls,
          ))

    # Skip empty sessions
    if not exchanges:
      return None

    # Derive project name
    project_slug = path.parent.name
    project = _extract_project_from_slug(project_slug)
    if cwd:
      project = _extract_project_name(cwd)

    # Store relative path instead of absolute to avoid leaking user directory structure
    try:
      relative_path = str(path.relative_to(self.history_path))
    except ValueError:
      relative_path = path.name

    return AgentSession(
      id=session_id or path.stem,
      source="claude-code",
      project=project,
      started_at=first_timestamp,
      ended_at=last_timestamp,
      working_directory=cwd,
      exchanges=exchanges,
      git_branch=git_branch or None,
      files_touched=sorted(files_touched),
      metadata={
        "session_file": relative_path,
        "project_slug": project_slug,
      },
    )
