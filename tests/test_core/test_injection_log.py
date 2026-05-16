"""Tests for the best-effort UserPromptSubmit injection log."""

import json
import tempfile
from pathlib import Path

from agentvault.hooks.injection_log import (
  _MAX_LINES,
  _prompt_hash,
  read_log,
  record_injection,
)


def _path() -> Path:
  return Path(tempfile.mkdtemp()) / "injection_log.jsonl"


def test_prompt_hash_is_stable_and_truncated():
  h = _prompt_hash("hello there")
  assert isinstance(h, str)
  assert len(h) == 16
  assert h == _prompt_hash("hello there")


def test_prompt_hash_different_for_different_inputs():
  assert _prompt_hash("a") != _prompt_hash("b")


def test_record_appends_jsonl_line():
  path = _path()
  record_injection(
    path,
    prompt="anything",
    project="proj-a",
    session_id="s1",
    chunk_ids=["c1", "c2"],
    now=1000.0,
  )
  text = path.read_text()
  data = json.loads(text.strip())
  assert data["project"] == "proj-a"
  assert data["session_id"] == "s1"
  assert data["chunk_ids"] == ["c1", "c2"]
  assert data["ts"] == 1000.0
  assert "prompt_hash" in data
  # Plaintext prompt must never land in the log.
  assert "anything" not in text


def test_record_appends_multiple_calls():
  path = _path()
  for i in range(3):
    record_injection(
      path, prompt=f"p{i}", project="p", session_id="s",
      chunk_ids=[f"c{i}"], now=1000.0 + i,
    )
  records = read_log(path)
  assert len(records) == 3
  assert [r["chunk_ids"][0] for r in records] == ["c0", "c1", "c2"]


def test_read_log_missing_file_returns_empty():
  assert read_log(Path("/no/such/path.jsonl")) == []


def test_read_log_skips_malformed_lines():
  path = _path()
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(
    '{"ts": 1, "chunk_ids": []}\n'
    "garbage line\n"
    '{"ts": 2, "chunk_ids": ["x"]}\n'
  )
  out = read_log(path)
  assert len(out) == 2
  assert out[0]["ts"] == 1


def test_record_fails_open_on_unwritable_path():
  # Writing to a path whose parent doesn't exist *and* can't be created
  # (because it's under a non-directory) should not raise.
  blocker = Path(tempfile.mkdtemp()) / "blocker"
  blocker.write_text("file, not dir")
  bad = blocker / "child" / "injection_log.jsonl"
  # Must not raise.
  record_injection(
    bad, prompt="x", project=None, session_id=None, chunk_ids=[],
  )


def test_max_lines_constant_reasonable():
  # Just a guard against an accidental zero or huge value.
  assert 100 <= _MAX_LINES <= 100_000
