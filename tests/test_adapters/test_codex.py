"""Tests for Codex adapter."""

from pathlib import Path

from agentvault.adapters.codex import CodexAdapter

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_parse_session():
  adapter = CodexAdapter()
  session = adapter.parse_session(FIXTURES / "sample_codex_session.jsonl")

  assert session is not None
  assert session.source == "codex"
  assert session.id == "test-codex-001"
  assert session.project == "webapp"


def test_git_metadata():
  adapter = CodexAdapter()
  session = adapter.parse_session(FIXTURES / "sample_codex_session.jsonl")

  assert session.git_branch == "feature/auth"
  assert "abc123def" in session.git_commits


def test_exchange_count():
  adapter = CodexAdapter()
  session = adapter.parse_session(FIXTURES / "sample_codex_session.jsonl")

  human_msgs = [e for e in session.exchanges if e.role == "human"]
  assistant_msgs = [e for e in session.exchanges if e.role == "assistant"]

  assert len(human_msgs) == 2
  assert len(assistant_msgs) == 2


def test_skips_environment_context():
  adapter = CodexAdapter()
  session = adapter.parse_session(FIXTURES / "sample_codex_session.jsonl")

  for ex in session.exchanges:
    assert "environment_context" not in ex.content


def test_tool_calls():
  adapter = CodexAdapter()
  session = adapter.parse_session(FIXTURES / "sample_codex_session.jsonl")

  # First assistant response should have the shell tool call
  first_assistant = [e for e in session.exchanges if e.role == "assistant"][0]
  assert len(first_assistant.tool_calls) == 1
  assert first_assistant.tool_calls[0].name == "shell"


def test_timestamps():
  adapter = CodexAdapter()
  session = adapter.parse_session(FIXTURES / "sample_codex_session.jsonl")

  assert session.started_at == "2026-01-15T10:00:00.000Z"
  assert session.ended_at == "2026-01-15T10:01:10.000Z"


def test_deduplicates_messages():
  adapter = CodexAdapter()
  session = adapter.parse_session(FIXTURES / "sample_codex_session.jsonl")

  # "Can you add JWT..." appears in both event_msg and response_item
  # but the user message should only appear once
  jwt_user_msgs = [
    e for e in session.exchanges
    if "JWT" in e.content and e.role == "human"
  ]
  assert len(jwt_user_msgs) == 1
