"""Tests for Cursor adapter."""

import json
from pathlib import Path

from agentvault.adapters.cursor import CursorAdapter, _epoch_ms_to_iso, _extract_message

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_epoch_ms_to_iso():
  # 2024-01-01T00:00:00Z = 1704067200000ms
  result = _epoch_ms_to_iso(1704067200000)
  assert "2024-01-01" in result


def test_epoch_ms_to_iso_none():
  assert _epoch_ms_to_iso(None) == ""
  assert _epoch_ms_to_iso(0) == ""


def test_extract_user_message():
  msg = {"type": 1, "text": "Hello world", "bubbleId": "b1"}
  exchange = _extract_message(msg)

  assert exchange is not None
  assert exchange.role == "human"
  assert exchange.content == "Hello world"


def test_extract_assistant_message():
  msg = {"type": 2, "text": "I can help with that.", "bubbleId": "b2"}
  exchange = _extract_message(msg)

  assert exchange is not None
  assert exchange.role == "assistant"
  assert exchange.content == "I can help with that."


def test_extract_empty_message():
  msg = {"type": 1, "text": "", "bubbleId": "b3"}
  assert _extract_message(msg) is None


def test_extract_unknown_type():
  msg = {"type": 99, "text": "unknown", "bubbleId": "b4"}
  assert _extract_message(msg) is None


def test_parse_conversation_from_fixture():
  """Test parsing a conversation JSON directly (simulating DB read)."""
  fixture = FIXTURES / "sample_cursor_conversation.json"
  data = json.loads(fixture.read_text())

  # Simulate what the adapter does
  messages = data.get("conversation", [])
  assert len(messages) == 4

  exchanges = []
  for msg in messages:
    ex = _extract_message(msg)
    if ex:
      exchanges.append(ex)

  assert len(exchanges) == 4

  human_msgs = [e for e in exchanges if e.role == "human"]
  assistant_msgs = [e for e in exchanges if e.role == "assistant"]
  assert len(human_msgs) == 2
  assert len(assistant_msgs) == 2


def test_conversation_content():
  fixture = FIXTURES / "sample_cursor_conversation.json"
  data = json.loads(fixture.read_text())

  messages = data.get("conversation", [])
  first = _extract_message(messages[0])
  assert "dark mode" in first.content


def test_metadata_from_fixture():
  fixture = FIXTURES / "sample_cursor_conversation.json"
  data = json.loads(fixture.read_text())

  assert data["composerId"] == "test-cursor-001"
  assert data["name"] == "Add dark mode support"
  assert data["modelConfig"]["modelName"] == "claude-4-sonnet"
  assert data["_v"] == 5
