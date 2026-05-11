"""Tests for Obsidian writer security — path traversal, sanitization, redaction."""

import os
import tempfile
from pathlib import Path

import pytest

from agentvault.core.schema import AgentSession, Exchange
from agentvault.writers.obsidian import (
  MAX_BYTES_PER_EXCHANGE,
  MAX_EXCHANGES_HEAD,
  MAX_EXCHANGES_TAIL,
  MAX_TRANSCRIPT_BYTES,
  _sanitize_path_component,
  _truncate_utf8,
  write_daily_digest,
  write_session,
)


def _make_session(
  project: str = "test-project",
  session_id: str = "abc12345-session",
  started_at: str = "2026-04-01T10:00:00.000Z",
  content: str = "Hello world",
) -> AgentSession:
  return AgentSession(
    id=session_id,
    source="claude-code",
    project=project,
    started_at=started_at,
    ended_at="2026-04-01T11:00:00.000Z",
    working_directory="/Users/test/projects/myapp",
    exchanges=[
      Exchange(role="human", content=content, timestamp=started_at),
      Exchange(role="assistant", content="Got it.", timestamp=started_at),
    ],
  )


class TestSanitizePathComponent:
  def test_normal_name(self):
    assert _sanitize_path_component("my-project") == "my-project"

  def test_dots_stripped(self):
    result = _sanitize_path_component("..")
    assert ".." not in result

  def test_slashes_replaced(self):
    result = _sanitize_path_component("../../etc/passwd")
    assert "/" not in result
    assert "\\" not in result

  def test_null_bytes_replaced(self):
    result = _sanitize_path_component("project\x00name")
    assert "\x00" not in result

  def test_pipe_replaced(self):
    result = _sanitize_path_component("project|name")
    assert "|" not in result

  def test_brackets_replaced(self):
    result = _sanitize_path_component("project]]name")
    assert "]]" not in result


class TestWriteSession:
  def test_creates_file(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      vault = Path(tmpdir)
      session = _make_session()
      filepath = write_session(session, vault)

      assert filepath.exists()
      assert filepath.suffix == ".md"

  def test_file_permissions(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      vault = Path(tmpdir)
      session = _make_session()
      filepath = write_session(session, vault)

      mode = oct(os.stat(filepath).st_mode & 0o777)
      assert mode == "0o600"

  def test_path_traversal_blocked(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      vault = Path(tmpdir)
      session = _make_session(project="../../etc")
      # Should not raise — sanitization converts .. to safe string
      filepath = write_session(session, vault)
      assert filepath.resolve().is_relative_to(vault.resolve())

  def test_redacts_secrets_in_content(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      vault = Path(tmpdir)
      session = _make_session(content="My API key is sk-1234567890abcdefghijklmnop")
      filepath = write_session(session, vault)

      text = filepath.read_text()
      assert "sk-1234567890" not in text
      assert "[REDACTED]" in text

  def test_relative_file_paths(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      vault = Path(tmpdir)
      session = _make_session()
      session.files_touched = ["/Users/test/projects/myapp/src/main.py"]
      filepath = write_session(session, vault)

      text = filepath.read_text()
      assert "/Users/test/projects/myapp/src/main.py" not in text
      assert "src/main.py" in text


class TestSizeCaps:
  """Regression coverage for the 12 MB session files that hung Obsidian (v0.8.1)."""

  def test_truncate_utf8_short_string_is_unchanged(self):
    assert _truncate_utf8("hello", 100) == "hello"

  def test_truncate_utf8_caps_long_string(self):
    long_text = "x" * 5000
    out = _truncate_utf8(long_text, 1000)
    assert len(out.encode("utf-8")) < len(long_text.encode("utf-8"))
    assert "truncated" in out

  def test_truncate_utf8_respects_codepoint_boundaries(self):
    # Each "✓" is 3 UTF-8 bytes; cutting mid-codepoint would corrupt the string.
    text = "✓" * 200
    out = _truncate_utf8(text, 50)
    # Should round-trip cleanly with no replacement chars
    assert "�" not in out

  def test_per_exchange_content_is_truncated(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      vault = Path(tmpdir)
      huge_content = "A" * (MAX_BYTES_PER_EXCHANGE * 10)
      session = AgentSession(
        id="big-session-1",
        source="claude-code",
        project="test-project",
        started_at="2026-04-01T10:00:00.000Z",
        ended_at="2026-04-01T11:00:00.000Z",
        working_directory="/Users/test/projects/myapp",
        exchanges=[
          Exchange(role="human", content=huge_content, timestamp="2026-04-01T10:00:00.000Z"),
          Exchange(role="assistant", content=huge_content, timestamp="2026-04-01T10:01:00.000Z"),
        ],
      )
      filepath = write_session(session, vault)
      text = filepath.read_text()
      # Each exchange should be capped, not written in full.
      assert text.count("A" * MAX_BYTES_PER_EXCHANGE) <= 2
      assert "truncated" in text

  def test_long_session_keeps_only_head_and_tail(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      vault = Path(tmpdir)
      total = MAX_EXCHANGES_HEAD + MAX_EXCHANGES_TAIL + 50
      exchanges = [
        Exchange(
          role="human" if i % 2 == 0 else "assistant",
          content=f"exchange-{i}-payload",
          timestamp="2026-04-01T10:00:00.000Z",
        )
        for i in range(total)
      ]
      session = AgentSession(
        id="big-session-2",
        source="claude-code",
        project="test-project",
        started_at="2026-04-01T10:00:00.000Z",
        ended_at="2026-04-01T11:00:00.000Z",
        working_directory="/Users/test/projects/myapp",
        exchanges=exchanges,
      )
      filepath = write_session(session, vault)
      text = filepath.read_text()
      assert "exchange-0-payload" in text  # head retained
      assert f"exchange-{total - 1}-payload" in text  # tail retained
      assert "exchange-31-payload" not in text  # middle omitted
      assert "exchanges omitted" in text

  def test_total_file_size_stays_under_cap(self):
    """The whole point of v0.8.1: no single session file should exceed the cap."""
    with tempfile.TemporaryDirectory() as tmpdir:
      vault = Path(tmpdir)
      # Worst-case: lots of long exchanges
      exchanges = [
        Exchange(
          role="human" if i % 2 == 0 else "assistant",
          content="X" * 50_000,  # 50 KB each — would balloon to 5 MB without caps
          timestamp="2026-04-01T10:00:00.000Z",
        )
        for i in range(100)
      ]
      session = AgentSession(
        id="big-session-3",
        source="claude-code",
        project="test-project",
        started_at="2026-04-01T10:00:00.000Z",
        ended_at="2026-04-01T11:00:00.000Z",
        working_directory="/Users/test/projects/myapp",
        exchanges=exchanges,
      )
      filepath = write_session(session, vault)
      size = filepath.stat().st_size
      # Allow some headroom over MAX_TRANSCRIPT_BYTES for frontmatter + headers
      assert size < MAX_TRANSCRIPT_BYTES + 50_000


class TestWriteDailyDigest:
  def test_creates_file(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      vault = Path(tmpdir)
      sessions = [_make_session()]
      filepath = write_daily_digest(sessions, vault, date="2026-04-01")

      assert filepath.exists()
      assert "2026-04-01" in filepath.name

  def test_file_permissions(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      vault = Path(tmpdir)
      sessions = [_make_session()]
      filepath = write_daily_digest(sessions, vault, date="2026-04-01")

      mode = oct(os.stat(filepath).st_mode & 0o777)
      assert mode == "0o600"

  def test_path_traversal_in_date_blocked(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      vault = Path(tmpdir)
      sessions = [_make_session()]
      # Malicious date value
      filepath = write_daily_digest(sessions, vault, date="../../etc")
      assert filepath.resolve().is_relative_to(vault.resolve())

  def test_sanitized_wikilinks(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      vault = Path(tmpdir)
      session = _make_session(project="evil]]|inject")
      filepath = write_daily_digest([session], vault, date="2026-04-01")

      text = filepath.read_text()
      assert "]]|" not in text
