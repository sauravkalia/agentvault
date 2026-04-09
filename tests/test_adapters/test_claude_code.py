"""Tests for Claude Code adapter."""

from pathlib import Path

from agentvault.adapters.claude_code import ClaudeCodeAdapter

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_parse_sample_session():
  adapter = ClaudeCodeAdapter()
  session = adapter.parse_session(FIXTURES / "sample_claude_session.jsonl")

  assert session is not None
  assert session.source == "claude-code"
  assert session.project == "myapp"
  assert session.git_branch == "feature/auth"
  assert session.id == "test-session-001"


def test_exchange_count():
  adapter = ClaudeCodeAdapter()
  session = adapter.parse_session(FIXTURES / "sample_claude_session.jsonl")

  # 2 user + 2 assistant = 4 exchanges
  assert len(session.exchanges) == 4

  human_msgs = [e for e in session.exchanges if e.role == "human"]
  assert len(human_msgs) == 2

  assistant_msgs = [e for e in session.exchanges if e.role == "assistant"]
  assert len(assistant_msgs) == 2


def test_tool_calls_extracted():
  adapter = ClaudeCodeAdapter()
  session = adapter.parse_session(FIXTURES / "sample_claude_session.jsonl")

  # Last assistant message used the Write tool
  last_assistant = [e for e in session.exchanges if e.role == "assistant"][-1]
  assert len(last_assistant.tool_calls) == 1
  assert last_assistant.tool_calls[0].name == "Write"


def test_files_touched():
  adapter = ClaudeCodeAdapter()
  session = adapter.parse_session(FIXTURES / "sample_claude_session.jsonl")

  assert "/Users/test/projects/myapp/src/middleware.ts" in session.files_touched


def test_timestamps():
  adapter = ClaudeCodeAdapter()
  session = adapter.parse_session(FIXTURES / "sample_claude_session.jsonl")

  assert session.started_at == "2026-04-01T10:00:00.000Z"
  assert session.ended_at == "2026-04-01T10:01:30.000Z"
