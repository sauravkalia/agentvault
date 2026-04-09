"""Common schema for agent sessions across all tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class ToolCall:
  """A tool invocation by the AI agent."""

  name: str
  input: dict[str, Any] = field(default_factory=dict)
  output: Optional[str] = None


@dataclass
class Exchange:
  """A single message in the conversation."""

  role: str  # "human", "assistant", "system"
  content: str
  timestamp: str
  tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class AgentSession:
  """Unified session format — every adapter converts to this."""

  id: str
  source: str  # "claude-code", "opencode", "codex", "cursor", "chatgpt"
  project: str
  started_at: str
  ended_at: str
  working_directory: str
  exchanges: list[Exchange] = field(default_factory=list)
  summary: Optional[str] = None
  tags: list[str] = field(default_factory=list)
  files_touched: list[str] = field(default_factory=list)
  git_branch: Optional[str] = None
  git_commits: list[str] = field(default_factory=list)
  metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chunk:
  """A chunk of conversation ready for embedding."""

  id: str
  session_id: str
  source: str
  project: str
  content: str
  timestamp: str
  git_branch: Optional[str] = None
  chunk_index: int = 0
  metadata: dict[str, Any] = field(default_factory=dict)

  def to_chromadb_metadata(self) -> dict[str, str]:
    """Flatten metadata for ChromaDB (only str/int/float/bool allowed)."""
    return {
      "session_id": self.session_id,
      "source": self.source,
      "project": self.project,
      "timestamp": self.timestamp,
      "git_branch": self.git_branch or "",
      "chunk_index": self.chunk_index,
    }
