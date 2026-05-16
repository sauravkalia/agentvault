"""Tests for the Aider adapter."""

import shutil
import tempfile
from pathlib import Path

from agentvault.adapters.aider import (
  AiderAdapter,
  _normalize_ts,
  _split_into_sessions,
  _walk_for_aider_files,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
SAMPLE = FIXTURES / "sample_aider_chat.md"


def test_parse_session_basic():
  adapter = AiderAdapter()
  session = adapter.parse_session(SAMPLE)
  assert session is not None
  assert session.source == "aider"
  # File lives under fixtures/, so project name should be "fixtures".
  assert session.project == "fixtures"


def test_parse_session_combines_sessions_in_one_file():
  """Aider stores many chat sessions in one file; the adapter returns a
  single AgentSession that preserves all of them in `exchanges`."""
  adapter = AiderAdapter()
  session = adapter.parse_session(SAMPLE)
  human = [e for e in session.exchanges if e.role == "human"]
  assistant = [e for e in session.exchanges if e.role == "assistant"]
  # Three user prompts across two sessions in the fixture.
  assert len(human) == 3
  assert len(assistant) == 3


def test_started_and_ended_at_span_all_sessions():
  adapter = AiderAdapter()
  session = adapter.parse_session(SAMPLE)
  assert session.started_at == "2026-01-10T14:30:00Z"
  assert session.ended_at == "2026-01-11T09:15:00Z"


def test_multiline_user_message_is_joined():
  """Two contiguous `#### ` lines should merge into one human exchange."""
  adapter = AiderAdapter()
  session = adapter.parse_session(SAMPLE)
  joined = [
    e for e in session.exchanges
    if e.role == "human" and "refresh tokens" in e.content
  ]
  assert len(joined) == 1
  assert "use redis as the backing store" in joined[0].content


def test_applied_edits_become_tool_calls_and_files_touched():
  adapter = AiderAdapter()
  session = adapter.parse_session(SAMPLE)

  # Three "Applied edit to ..." lines across the fixture; auth.py
  # appears twice but files_touched is deduped.
  assert "auth.py" in session.files_touched
  assert "tests/test_auth.py" in session.files_touched
  assert len(session.files_touched) == 2

  # Each assistant exchange that immediately precedes an edit notice
  # should carry an edit_file ToolCall.
  edit_tool_calls = [
    tc
    for e in session.exchanges
    for tc in e.tool_calls
    if tc.name == "edit_file"
  ]
  assert len(edit_tool_calls) == 3
  assert any(tc.input.get("path") == "auth.py" for tc in edit_tool_calls)


def test_tool_notice_lines_dont_leak_into_content():
  adapter = AiderAdapter()
  session = adapter.parse_session(SAMPLE)
  for e in session.exchanges:
    assert not e.content.startswith(">"), e.content[:50]
    assert "Applied edit to" not in e.content


def test_session_id_is_stable_for_same_file():
  adapter = AiderAdapter()
  s1 = adapter.parse_session(SAMPLE)
  s2 = adapter.parse_session(SAMPLE)
  assert s1.id == s2.id


def test_parse_empty_file_returns_none():
  tmp = Path(tempfile.mkdtemp()) / ".aider.chat.history.md"
  tmp.write_text("", encoding="utf-8")
  adapter = AiderAdapter()
  assert adapter.parse_session(tmp) is None


def test_parse_file_without_header_returns_none():
  tmp = Path(tempfile.mkdtemp()) / ".aider.chat.history.md"
  tmp.write_text("just some random text\nno aider header here", encoding="utf-8")
  adapter = AiderAdapter()
  assert adapter.parse_session(tmp) is None


def test_normalize_timestamp():
  assert _normalize_ts("2026-01-10 14:30:00") == "2026-01-10T14:30:00Z"


def test_normalize_timestamp_fallback_on_bad_input():
  assert _normalize_ts("garbage") == "garbage"


def test_split_into_sessions_counts_headers():
  text = SAMPLE.read_text(encoding="utf-8")
  sessions = _split_into_sessions(text)
  assert len(sessions) == 2
  assert sessions[0][0] == "2026-01-10T14:30:00Z"
  assert sessions[1][0] == "2026-01-11T09:15:00Z"


def test_walk_skips_dot_and_heavy_dirs():
  root = Path(tempfile.mkdtemp())
  try:
    # Real project file — should be picked up.
    proj = root / "good-project"
    proj.mkdir()
    (proj / ".aider.chat.history.md").write_text(
      "# aider chat started at 2026-01-10 14:30:00\n", encoding="utf-8",
    )
    # Inside node_modules — must be pruned.
    nm = root / "good-project" / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / ".aider.chat.history.md").write_text(
      "# aider chat started at 2026-02-02 02:02:02\n", encoding="utf-8",
    )
    # Inside a dot-dir — must be pruned.
    cache = root / ".cache"
    cache.mkdir()
    (cache / ".aider.chat.history.md").write_text(
      "# aider chat started at 2026-02-02 02:02:02\n", encoding="utf-8",
    )

    hits = list(_walk_for_aider_files(root))
    assert len(hits) == 1
    assert hits[0].parent.name == "good-project"
  finally:
    shutil.rmtree(root, ignore_errors=True)


def test_detect_and_discover_use_history_path():
  root = Path(tempfile.mkdtemp())
  try:
    proj = root / "a-project"
    proj.mkdir()
    (proj / ".aider.chat.history.md").write_text(
      "# aider chat started at 2026-01-10 14:30:00\n\n#### hi\n\nhello\n",
      encoding="utf-8",
    )
    adapter = AiderAdapter(history_path=root)
    assert adapter.detect() is True
    sessions = adapter.discover_sessions()
    assert len(sessions) == 1
    parsed = adapter.parse_session(sessions[0])
    assert parsed is not None
    assert parsed.project == "a-project"
  finally:
    shutil.rmtree(root, ignore_errors=True)


def test_detect_returns_false_when_path_missing():
  adapter = AiderAdapter(history_path=Path("/nonexistent-aider-root-xyz"))
  assert adapter.detect() is False
  assert adapter.discover_sessions() == []
