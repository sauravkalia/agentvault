"""Base adapter interface — every AI tool adapter implements this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from agentvault.core.schema import AgentSession


class BaseAdapter(ABC):
  """Interface for AI tool history adapters.

  To add support for a new AI tool, create a new file in adapters/
  and implement these 3 methods.
  """

  name: str  # e.g. "claude-code", "opencode", "cursor"
  description: str  # human-readable description

  def __init__(self, history_path: Path | None = None):
    self.history_path = history_path or self.default_history_path()

  @abstractmethod
  def default_history_path(self) -> Path:
    """Default location where this tool stores history."""
    ...

  @abstractmethod
  def detect(self) -> bool:
    """Check if this tool's history exists on this machine."""
    ...

  @abstractmethod
  def discover_sessions(self) -> list[Path]:
    """Find all session files. Returns paths to raw session data."""
    ...

  @abstractmethod
  def parse_session(self, path: Path) -> AgentSession | None:
    """Convert a native session file into the common AgentSession schema.

    Returns None if the session should be skipped (e.g. empty, corrupt).
    """
    ...

  def get_all_sessions(self) -> list[AgentSession]:
    """Discover and parse all sessions. Convenience method."""
    sessions = []
    for path in self.discover_sessions():
      session = self.parse_session(path)
      if session:
        sessions.append(session)
    return sessions
