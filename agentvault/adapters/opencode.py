"""Adapter for OpenCode conversation history.

OpenCode stores prompt history at:
  ~/.local/state/opencode/prompt-history.jsonl

Each line: {"input": "user prompt", "parts": [], "mode": "normal"}

Limitation: Only user prompts are stored — no assistant responses or timestamps.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from agentvault.adapters.base import BaseAdapter
from agentvault.core.schema import AgentSession, Exchange


class OpenCodeAdapter(BaseAdapter):
  name = "opencode"
  description = "OpenCode CLI prompt history"

  def default_history_path(self) -> Path:
    return Path.home() / ".local" / "state" / "opencode"

  def detect(self) -> bool:
    history_file = self.history_path / "prompt-history.jsonl"
    return history_file.exists() and history_file.stat().st_size > 0

  def discover_sessions(self) -> list[Path]:
    """OpenCode stores all prompts in a single file."""
    history_file = self.history_path / "prompt-history.jsonl"
    if history_file.exists():
      return [history_file]
    return []

  def parse_session(self, path: Path) -> AgentSession | None:
    """Parse the prompt history file into a single session.

    Since OpenCode doesn't store timestamps or assistant responses,
    we treat the entire file as one session with user-only exchanges.
    """
    lines = path.read_text(
      encoding="utf-8", errors="replace"
    ).strip().split("\n")
    if not lines:
      return None

    exchanges: list[Exchange] = []
    file_mtime = datetime.fromtimestamp(
      os.path.getmtime(path)
    ).isoformat() + "Z"

    for line in lines:
      try:
        obj = json.loads(line)
      except json.JSONDecodeError:
        continue

      prompt = obj.get("input", "").strip()
      if not prompt:
        continue

      exchanges.append(Exchange(
        role="human",
        content=prompt,
        timestamp=file_mtime,
      ))

    if not exchanges:
      return None

    return AgentSession(
      id=f"opencode-{path.stem}",
      source="opencode",
      project="general",
      started_at=file_mtime,
      ended_at=file_mtime,
      working_directory="",
      exchanges=exchanges,
      metadata={
        "session_file": path.name,
        "note": "OpenCode only stores user prompts, "
                "no assistant responses or timestamps",
      },
    )
