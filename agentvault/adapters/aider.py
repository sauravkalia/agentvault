"""Adapter for Aider chat history.

Aider stores per-project chat history in `.aider.chat.history.md` at the
working directory root. There is no central directory — every project has
its own file. Format (from aider/history.py):

  # aider chat started at 2026-01-10 14:30:00

  > Repo-map: ...
  > Files added to chat: ...

  #### Can you refactor the auth module?

  Sure! I'll look at the auth module first.

  ```python
  def authenticate(...): ...
  ```

  > Applied edit to auth.py

  #### Now add tests for that
  ...

Rules:
  - `# aider chat started at <ts>` separates sessions inside one file.
  - `#### ` (four hashes + space) prefixes each line of a user message;
    contiguous `####` lines are one message.
  - `> ` lines are tool / system output. We pull file-edit confirmations
    ("Applied edit to <path>") out as ToolCall hints; the rest is dropped.
  - Everything else is assistant prose (kept verbatim, including fenced
    code blocks).
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Iterator

from agentvault.adapters.base import BaseAdapter
from agentvault.core.schema import AgentSession, Exchange, ToolCall

SESSION_HEADER_RE = re.compile(
  r"^# aider chat started at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*$"
)
APPLIED_EDIT_RE = re.compile(r"^> Applied edit to (.+?)\s*$")

# Directories to skip when walking for `.aider.chat.history.md`. Keeps
# `discover_sessions` from grinding through caches and vendored deps.
_SKIP_DIRS = {
  ".git", ".hg", ".svn",
  "node_modules", "bower_components",
  ".venv", "venv", ".env", "env",
  "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
  ".tox", ".nox", ".cache", ".npm", ".yarn", ".pnpm-store",
  ".cargo", ".rustup", ".pyenv", ".rbenv", ".nvm",
  "Library", "Trash", ".Trash",
  "dist", "build", "target", "out",
  ".next", ".nuxt", ".turbo", ".vercel",
  "DerivedData", ".gradle",
}
_MAX_WALK_DEPTH = 6


def _walk_for_aider_files(root: Path, max_depth: int = _MAX_WALK_DEPTH) -> Iterator[Path]:
  """Yield every `.aider.chat.history.md` under `root`, depth-capped and
  pruning known-heavy / dot-prefixed directories.
  """
  root = root.resolve()
  root_str = str(root)
  base_depth = root_str.rstrip(os.sep).count(os.sep)

  for dirpath, dirnames, filenames in os.walk(root_str, followlinks=False):
    depth = dirpath.count(os.sep) - base_depth
    if depth >= max_depth:
      dirnames[:] = []
      continue
    dirnames[:] = [
      d for d in dirnames
      if d not in _SKIP_DIRS and not d.startswith(".")
    ]
    if ".aider.chat.history.md" in filenames:
      yield Path(dirpath) / ".aider.chat.history.md"


def _normalize_ts(raw: str) -> str:
  """`2026-01-10 14:30:00` → `2026-01-10T14:30:00Z`."""
  try:
    dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
  except ValueError:
    return raw
  return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_session_body(lines: list[str], timestamp: str) -> tuple[
  list[Exchange], list[str]
]:
  """Parse one session's lines into exchanges and a list of edited files.

  Returns (exchanges, files_touched). Multi-line user messages are
  joined; `> Applied edit to <path>` lines become tool calls on the
  most recent assistant exchange.
  """
  exchanges: list[Exchange] = []
  files_touched: list[str] = []
  pending_user: list[str] = []
  pending_assistant: list[str] = []

  def flush_user() -> None:
    if pending_user:
      flush_assistant()
      exchanges.append(Exchange(
        role="human",
        content="\n".join(pending_user).strip(),
        timestamp=timestamp,
      ))
      pending_user.clear()

  def flush_assistant() -> None:
    text = "\n".join(pending_assistant).strip()
    if text:
      exchanges.append(Exchange(
        role="assistant",
        content=text,
        timestamp=timestamp,
      ))
    pending_assistant.clear()

  for line in lines:
    if line.startswith("#### "):
      flush_assistant()
      pending_user.append(line[5:])
      continue
    if line == "####":
      # Blank user-prefixed line — treat as paragraph break inside msg.
      flush_assistant()
      pending_user.append("")
      continue

    if pending_user:
      flush_user()

    if line.startswith(">"):
      # System / tool notice. Pull out file edits, drop the rest.
      m = APPLIED_EDIT_RE.match(line)
      if m:
        path = m.group(1).strip()
        if path and path not in files_touched:
          files_touched.append(path)
        tc = ToolCall(name="edit_file", input={"path": path})
        # Attach to the most recent assistant turn (creating one if the
        # edit came before any assistant prose, which is rare but legal).
        flush_assistant()
        if exchanges and exchanges[-1].role == "assistant":
          exchanges[-1].tool_calls.append(tc)
        else:
          exchanges.append(Exchange(
            role="assistant",
            content="",
            timestamp=timestamp,
            tool_calls=[tc],
          ))
      continue

    pending_assistant.append(line)

  flush_user()
  flush_assistant()
  return exchanges, files_touched


def _split_into_sessions(text: str) -> list[tuple[str, list[str]]]:
  """Split file text into (timestamp, body_lines) per `# aider chat started at` header."""
  sessions: list[tuple[str, list[str]]] = []
  current_ts: str | None = None
  current_body: list[str] = []

  for raw_line in text.splitlines():
    m = SESSION_HEADER_RE.match(raw_line)
    if m:
      if current_ts is not None:
        sessions.append((current_ts, current_body))
      current_ts = _normalize_ts(m.group(1))
      current_body = []
    else:
      if current_ts is None:
        # Skip preamble before first header — files without a header
        # have no parseable session.
        continue
      current_body.append(raw_line)

  if current_ts is not None:
    sessions.append((current_ts, current_body))

  return sessions


def _session_id(file_path: Path, timestamp: str) -> str:
  h = hashlib.sha1(f"{file_path}|{timestamp}".encode("utf-8")).hexdigest()
  return f"aider-{h[:16]}"


class AiderAdapter(BaseAdapter):
  name = "aider"
  description = "Aider AI coding CLI chat history"

  def default_history_path(self) -> Path:
    # No central history dir for Aider — walk from the user's home and
    # prune. Users with sprawling home directories should override this
    # in config to a tighter root (e.g. `~/Documents/GitHub`).
    return Path.home()

  def detect(self) -> bool:
    if not self.history_path.exists():
      return False
    # Don't pay the full walk just to check; first hit is enough.
    for _ in _walk_for_aider_files(self.history_path):
      return True
    return False

  def discover_sessions(self) -> list[Path]:
    if not self.history_path.exists():
      return []
    return sorted(_walk_for_aider_files(self.history_path))

  def parse_session(self, path: Path) -> AgentSession | None:
    """Parse a `.aider.chat.history.md` file. Returns the *most recent*
    session in the file as an AgentSession; older sessions in the same
    file are concatenated into the same session under the latest header
    so we don't lose them.

    Rationale: callers expect one AgentSession per file (matches the
    other adapters), but Aider re-uses one file across many sessions.
    We keep the newest session's start timestamp as the session id /
    started_at, and treat any earlier sessions in the file as prior
    context within the same logical "thread of work on this project".
    """
    try:
      text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
      return None

    sessions = _split_into_sessions(text)
    if not sessions:
      return None

    all_exchanges: list[Exchange] = []
    all_files: list[str] = []
    timestamps = [ts for ts, _ in sessions]
    for ts, body in sessions:
      ex, files = _parse_session_body(body, ts)
      all_exchanges.extend(ex)
      for f in files:
        if f not in all_files:
          all_files.append(f)

    if not all_exchanges:
      return None

    first_ts = timestamps[0]
    last_ts = timestamps[-1]
    cwd = str(path.parent)
    project = path.parent.name or "unknown"

    return AgentSession(
      id=_session_id(path, last_ts),
      source="aider",
      project=project,
      started_at=first_ts,
      ended_at=last_ts,
      working_directory=cwd,
      exchanges=all_exchanges,
      files_touched=all_files,
      metadata={
        "session_file": str(path),
        "session_count": len(sessions),
      },
    )
