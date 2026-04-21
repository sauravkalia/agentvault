"""Tests for VaultStore initialization with different path types."""

import tempfile
from pathlib import Path

from agentvault.core.store import VaultStore


def test_init_with_path():
  """VaultStore should accept a Path object."""
  tmpdir = tempfile.mkdtemp()
  store = VaultStore(persist_dir=Path(tmpdir), collection_name="test_path")
  assert store.persist_dir == Path(tmpdir)
  assert store.collection is not None


def test_init_with_string():
  """VaultStore should accept a string path (regression: v0.6.0 crashed on str).

  The MCP server passes config.get('chromadb_dir') which is a str from JSON,
  and this used to crash with: AttributeError: 'str' object has no attribute 'mkdir'
  """
  tmpdir = tempfile.mkdtemp()
  store = VaultStore(persist_dir=tmpdir, collection_name="test_str")
  assert isinstance(store.persist_dir, Path)
  assert store.persist_dir == Path(tmpdir)
  assert store.collection is not None


def test_init_with_none_uses_default():
  """VaultStore should use DEFAULT_CHROMADB_DIR when None passed."""
  from agentvault.config import DEFAULT_CHROMADB_DIR
  store = VaultStore(persist_dir=None, collection_name="test_default")
  assert store.persist_dir == DEFAULT_CHROMADB_DIR
