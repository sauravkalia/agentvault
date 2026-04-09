"""Tests for OpenCode adapter."""

from pathlib import Path

from agentvault.adapters.opencode import OpenCodeAdapter

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_parse_prompt_history():
  adapter = OpenCodeAdapter(history_path=FIXTURES)
  session = adapter.parse_session(FIXTURES / "sample_opencode_history.jsonl")

  assert session is not None
  assert session.source == "opencode"


def test_exchange_count():
  adapter = OpenCodeAdapter(history_path=FIXTURES)
  session = adapter.parse_session(FIXTURES / "sample_opencode_history.jsonl")

  # 3 user prompts, no assistant responses
  assert len(session.exchanges) == 3
  assert all(e.role == "human" for e in session.exchanges)


def test_prompt_content():
  adapter = OpenCodeAdapter(history_path=FIXTURES)
  session = adapter.parse_session(FIXTURES / "sample_opencode_history.jsonl")

  assert "authentication" in session.exchanges[0].content
  assert "rate limiting" in session.exchanges[1].content
  assert "file uploads" in session.exchanges[2].content


def test_metadata():
  adapter = OpenCodeAdapter(history_path=FIXTURES)
  session = adapter.parse_session(FIXTURES / "sample_opencode_history.jsonl")

  assert "note" in session.metadata
  assert "no assistant responses" in session.metadata["note"]
