"""Tests for store delete operations."""

import tempfile
from pathlib import Path

from agentvault.core.schema import Chunk
from agentvault.core.store import VaultStore


def _make_store():
  """Create a temporary store for testing."""
  tmpdir = tempfile.mkdtemp()
  return VaultStore(persist_dir=Path(tmpdir), collection_name="test_delete")


def _make_chunks(session_id="s1", project="proj-a", source="claude-code", count=3):
  return [
    Chunk(
      id=f"{session_id}-{i}",
      session_id=session_id,
      source=source,
      project=project,
      content=f"Test content {i}",
      timestamp="2026-04-01T10:00:00Z",
      chunk_index=i,
    )
    for i in range(count)
  ]


def test_delete_by_session():
  store = _make_store()
  store.add_chunks(_make_chunks("s1", "proj-a"))
  store.add_chunks(_make_chunks("s2", "proj-a"))

  deleted = store.delete_by_session("s1")
  assert deleted == 3
  assert store.collection.count() == 3  # s2 remains


def test_delete_by_project():
  store = _make_store()
  store.add_chunks(_make_chunks("s1", "proj-a"))
  store.add_chunks(_make_chunks("s2", "proj-b"))

  deleted = store.delete_by_project("proj-a")
  assert deleted == 3
  assert store.collection.count() == 3  # proj-b remains


def test_delete_by_source():
  store = _make_store()
  store.add_chunks(_make_chunks("s1", "proj-a", "claude-code"))
  store.add_chunks(_make_chunks("s2", "proj-a", "cursor"))

  deleted = store.delete_by_source("claude-code")
  assert deleted == 3
  assert store.collection.count() == 3  # cursor remains


def test_delete_all():
  store = _make_store()
  store.add_chunks(_make_chunks("s1"))
  store.add_chunks(_make_chunks("s2"))

  deleted = store.delete_all()
  assert deleted == 6
  assert store.collection.count() == 0


def test_delete_nonexistent():
  store = _make_store()
  store.add_chunks(_make_chunks("s1"))

  deleted = store.delete_by_session("nonexistent")
  assert deleted == 0
  assert store.collection.count() == 3
