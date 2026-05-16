"""Tests for the PreToolUse file-context hook helper."""

import json
import tempfile
import time
from pathlib import Path

from agentvault.hooks.file_context import (
  THROTTLE_MAX_ENTRIES,
  THROTTLE_SECONDS,
  _basename_query,
  _format_block,
  _load_throttle,
  _prune_throttle,
  build_file_context,
)


class FakeStore:
  """Stand-in for VaultStore that records the last search args."""

  def __init__(self, results=None, raises: Exception | None = None):
    self.results = results or []
    self.raises = raises
    self.last_kwargs: dict | None = None

  def search(self, **kwargs):
    self.last_kwargs = kwargs
    if self.raises:
      raise self.raises
    return self.results


def _hit(content: str, project: str = "proj-a", source: str = "claude-code",
        ts: str = "2026-05-01T10:00:00Z") -> dict:
  return {
    "content": content,
    "metadata": {
      "project": project,
      "source": source,
      "timestamp": ts,
    },
    "distance": 0.2,
  }


def _throttle_path() -> Path:
  return Path(tempfile.mkdtemp()) / "throttle.json"


def test_basename_query_picks_filename():
  assert _basename_query("src/auth/jwt.py") == "jwt.py"
  assert _basename_query("auth.py") == "auth.py"
  assert _basename_query("/abs/path/foo.ts") == "foo.ts"


def test_basename_handles_trailing_slash():
  assert _basename_query("src/dir/") == "dir"


def test_build_returns_none_for_empty_path():
  out = build_file_context(
    "", "/tmp/proj", FakeStore([_hit("anything")]), _throttle_path(),
  )
  assert out is None


def test_build_returns_block_for_hits():
  store = FakeStore([_hit("we discussed JWT refresh tokens in this file")])
  out = build_file_context(
    "src/auth.py", "/tmp/proj-a", store, _throttle_path(),
  )
  assert out is not None
  assert "Past discussion of `src/auth.py`" in out
  assert "JWT refresh tokens" in out
  assert "[proj-a · claude-code · 2026-05-01]" in out


def test_build_returns_none_when_no_hits():
  out = build_file_context(
    "src/auth.py", "/tmp/proj", FakeStore([]), _throttle_path(),
  )
  assert out is None


def test_build_returns_none_on_store_exception():
  store = FakeStore(raises=RuntimeError("chroma blew up"))
  out = build_file_context(
    "src/auth.py", "/tmp/proj", store, _throttle_path(),
  )
  assert out is None


def test_search_uses_basename_and_project_and_hybrid_mode():
  store = FakeStore([_hit("hit")])
  build_file_context(
    "src/auth/jwt.py", "/Users/me/proj-a", store, _throttle_path(),
  )
  assert store.last_kwargs is not None
  assert store.last_kwargs["query"] == "jwt.py"
  assert store.last_kwargs["project"] == "proj-a"
  assert store.last_kwargs["mode"] == "hybrid"


def test_throttle_skips_repeat_within_window():
  path = _throttle_path()
  store = FakeStore([_hit("first")])
  first = build_file_context(
    "src/auth.py", "/tmp/proj", store, path, now=1000.0,
  )
  assert first is not None

  # Same path 5s later — must be skipped.
  store.results = [_hit("second")]
  second = build_file_context(
    "src/auth.py", "/tmp/proj", store, path, now=1005.0,
  )
  assert second is None


def test_throttle_allows_after_window():
  path = _throttle_path()
  store = FakeStore([_hit("first")])
  build_file_context(
    "src/auth.py", "/tmp/proj", store, path, now=1000.0,
  )
  # Past the window — should fire again.
  out = build_file_context(
    "src/auth.py", "/tmp/proj", store, path,
    now=1000.0 + THROTTLE_SECONDS + 1,
  )
  assert out is not None


def test_throttle_per_file_not_global():
  path = _throttle_path()
  store = FakeStore([_hit("hit")])
  a = build_file_context("a.py", "/tmp/proj", store, path, now=1000.0)
  b = build_file_context("b.py", "/tmp/proj", store, path, now=1001.0)
  assert a is not None
  assert b is not None


def test_throttle_file_written_atomically():
  path = _throttle_path()
  store = FakeStore([_hit("hit")])
  build_file_context("a.py", "/tmp/proj", store, path, now=1000.0)
  data = json.loads(path.read_text())
  assert data["a.py"] == 1000.0


def test_throttle_not_written_when_no_hits():
  path = _throttle_path()
  store = FakeStore([])
  build_file_context("a.py", "/tmp/proj", store, path, now=1000.0)
  assert not path.exists()


def test_load_throttle_tolerates_corrupt_file():
  path = _throttle_path()
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text("not json {{{")
  assert _load_throttle(path) == {}


def test_load_throttle_missing_file_returns_empty():
  assert _load_throttle(Path("/nope/missing.json")) == {}


def test_prune_drops_old_entries():
  now = 10_000.0
  data = {
    "fresh.py": now - 30,
    "stale.py": now - (THROTTLE_SECONDS * 4 + 10),
  }
  out = _prune_throttle(data, now)
  assert "fresh.py" in out
  assert "stale.py" not in out


def test_prune_caps_size():
  now = 10_000.0
  data = {f"f{i}.py": now - i for i in range(THROTTLE_MAX_ENTRIES + 50)}
  out = _prune_throttle(data, now)
  assert len(out) <= THROTTLE_MAX_ENTRIES


def test_format_block_truncates_long_snippet():
  hit = _hit("x" * 1000)
  block = _format_block("a.py", [hit])
  assert "…" in block


def test_no_project_when_cwd_empty():
  store = FakeStore([_hit("hit")])
  build_file_context("a.py", "", store, _throttle_path())
  assert store.last_kwargs is not None
  assert store.last_kwargs["project"] is None


def test_now_advances_default_to_wall_clock():
  """When `now` isn't passed, the helper uses time.time(). Smoke-check
  that the throttle write happens (which means we got past the timestamp
  comparison)."""
  path = _throttle_path()
  store = FakeStore([_hit("hit")])
  before = time.time() - 1
  out = build_file_context("a.py", "/tmp/proj", store, path)
  after = time.time() + 1
  assert out is not None
  data = json.loads(path.read_text())
  assert before <= data["a.py"] <= after
