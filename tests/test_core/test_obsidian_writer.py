"""Tests for Obsidian writer security — path traversal, sanitization, redaction."""

import os
import tempfile
from pathlib import Path

import pytest

from agentvault.core.schema import AgentSession, Exchange
from agentvault.writers.obsidian import (
  _sanitize_path_component,
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
