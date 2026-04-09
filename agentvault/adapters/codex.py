"""Adapter for OpenAI Codex CLI conversation history.

Codex stores sessions as JSONL files at:
  ~/.codex/sessions/{YYYY}/{MM}/{DD}/rollout-{timestamp}-{id}.jsonl

Each line is a JSON event with fields:
  - timestamp: ISO 8601
  - type: "session_meta" | "response_item" | "event_msg" | "function_call"
  - payload: type-specific data

session_meta payload has: id, cwd, git (branch, commit_hash, repository_url)
response_item payload has: type, role, content (list of input_text/output_text)
function_call payload has: name, arguments (JSON string)
"""

from __future__ import annotations

import json
from pathlib import Path

from agentvault.adapters.base import BaseAdapter
from agentvault.core.schema import AgentSession, Exchange, ToolCall


def _extract_text(content_blocks: list[dict]) -> str:
  """Extract text from Codex content blocks."""
  texts = []
  for block in content_blocks:
    if isinstance(block, dict):
      for key in ("text", "input_text", "output_text"):
        if key in block:
          texts.append(block[key])
  return "\n".join(texts)


def _parse_function_call(payload: dict) -> ToolCall | None:
  """Parse a function_call event into a ToolCall."""
  name = payload.get("name", "")
  if not name:
    return None
  args_str = payload.get("arguments", "{}")
  try:
    args = json.loads(args_str) if isinstance(args_str, str) else args_str
  except json.JSONDecodeError:
    args = {"raw": args_str}
  return ToolCall(name=name, input=args if isinstance(args, dict) else {})


class CodexAdapter(BaseAdapter):
  name = "codex"
  description = "OpenAI Codex CLI conversation history"

  def default_history_path(self) -> Path:
    return Path.home() / ".codex" / "sessions"

  def detect(self) -> bool:
    if not self.history_path.exists():
      return False
    return any(self.history_path.rglob("*.jsonl"))

  def discover_sessions(self) -> list[Path]:
    """Find all JSONL session files in dated directories."""
    if not self.history_path.exists():
      return []
    return sorted(self.history_path.rglob("*.jsonl"))

  def parse_session(self, path: Path) -> AgentSession | None:
    """Parse a Codex session JSONL file."""
    lines = path.read_text(
      encoding="utf-8", errors="replace"
    ).strip().split("\n")
    if not lines:
      return None

    exchanges: list[Exchange] = []
    session_id = ""
    cwd = ""
    git_branch = ""
    git_commit = ""
    first_timestamp = ""
    last_timestamp = ""
    seen_user_msgs: set[str] = set()

    for line in lines:
      try:
        obj = json.loads(line)
      except json.JSONDecodeError:
        continue

      timestamp = obj.get("timestamp", "")
      event_type = obj.get("type", "")
      payload = obj.get("payload", {})

      if timestamp:
        if not first_timestamp:
          first_timestamp = timestamp
        last_timestamp = timestamp

      if event_type == "session_meta":
        session_id = payload.get("id", "")
        cwd = payload.get("cwd", "")
        git_info = payload.get("git", {})
        git_branch = git_info.get("branch", "")
        git_commit = git_info.get("commit_hash", "")

      elif event_type == "response_item":
        role = payload.get("role", "")
        content = payload.get("content", [])
        if not isinstance(content, list):
          continue

        text = _extract_text(content)
        if not text.strip():
          continue

        # Skip environment_context blocks (system prompts)
        if "<environment_context>" in text:
          continue

        if role == "user":
          # Deduplicate — Codex often sends same message
          # in both response_item and event_msg
          msg_hash = text.strip()[:200]
          if msg_hash in seen_user_msgs:
            continue
          seen_user_msgs.add(msg_hash)

          exchanges.append(Exchange(
            role="human",
            content=text.strip(),
            timestamp=timestamp,
          ))

        elif role == "assistant":
          exchanges.append(Exchange(
            role="assistant",
            content=text.strip(),
            timestamp=timestamp,
          ))

      elif event_type == "event_msg":
        msg_type = payload.get("type", "")
        if msg_type == "user_message":
          text = payload.get("message", "").strip()
          if not text:
            continue
          msg_hash = text[:200]
          if msg_hash in seen_user_msgs:
            continue
          seen_user_msgs.add(msg_hash)

          exchanges.append(Exchange(
            role="human",
            content=text,
            timestamp=timestamp,
          ))

      elif event_type == "function_call":
        tc = _parse_function_call(payload)
        if tc and exchanges:
          # Attach tool call to the last assistant exchange
          last_assistant = None
          for ex in reversed(exchanges):
            if ex.role == "assistant":
              last_assistant = ex
              break
          if last_assistant:
            last_assistant.tool_calls.append(tc)

    if not exchanges:
      return None

    project = Path(cwd).name if cwd else "unknown"

    return AgentSession(
      id=session_id or path.stem,
      source="codex",
      project=project,
      started_at=first_timestamp,
      ended_at=last_timestamp,
      working_directory=cwd,
      exchanges=exchanges,
      git_branch=git_branch or None,
      git_commits=[git_commit] if git_commit else [],
      metadata={
        "session_file": path.name,
      },
    )
