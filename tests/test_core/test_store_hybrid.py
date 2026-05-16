"""Tests for hybrid + keyword search and FTS migration in VaultStore."""

import tempfile
from pathlib import Path

from agentvault.core.fts_index import FTSIndex
from agentvault.core.schema import Chunk
from agentvault.core.store import VaultStore, _min_max_normalize


def _make_store(name="test_hybrid"):
  tmpdir = tempfile.mkdtemp()
  return VaultStore(persist_dir=Path(tmpdir), collection_name=name), tmpdir


def _chunk(cid: str, content: str, **overrides):
  base = dict(
    id=cid,
    session_id="s1",
    source="claude-code",
    project="proj-a",
    content=content,
    timestamp="2026-05-01T00:00:00Z",
    git_branch="main",
    chunk_index=0,
  )
  base.update(overrides)
  return Chunk(**base)


def test_min_max_normalize_basic():
  assert _min_max_normalize([1.0, 2.0, 3.0]) == [0.0, 0.5, 1.0]


def test_min_max_normalize_identical_values():
  # Avoids divide-by-zero — all-equal collapses to 1.0.
  assert _min_max_normalize([5.0, 5.0, 5.0]) == [1.0, 1.0, 1.0]


def test_min_max_normalize_empty():
  assert _min_max_normalize([]) == []


def test_add_chunks_dual_writes_to_fts():
  store, _ = _make_store()
  store.add_chunks([_chunk("a", "hello world"), _chunk("b", "another")])
  assert store.collection.count() == 2
  assert store.fts.count() == 2


def test_keyword_mode_finds_exact_function_name():
  store, _ = _make_store("kw_exact")
  store.add_chunks([
    _chunk("1", "we should use useAuthProvider for the new login flow"),
    _chunk("2", "pasta recipes and other unrelated content"),
    _chunk("3", "general discussion about authentication patterns"),
  ])
  hits = store.search("useAuthProvider", top_k=3, mode="keyword")
  assert len(hits) >= 1
  assert hits[0]["id"] == "1"


def test_hybrid_mode_returns_combined_score():
  store, _ = _make_store("hybrid_combined")
  store.add_chunks([
    _chunk("1", "redirect redirect undefined redirect handling"),
    _chunk("2", "completely different topic about caching"),
  ])
  hits = store.search("redirect", top_k=2, mode="hybrid")
  assert len(hits) >= 1
  top = hits[0]
  assert top["id"] == "1"
  assert "score" in top
  assert "sem_score" in top
  assert "kw_score" in top
  assert 0.0 <= top["score"] <= 1.0


def test_semantic_mode_unchanged_behavior():
  store, _ = _make_store("semantic_only")
  store.add_chunks([_chunk("a", "the quick brown fox jumps")])
  hits = store.search("fox", top_k=5, mode="semantic")
  assert any(h["id"] == "a" for h in hits)
  # Semantic results carry distance (not a hybrid score).
  assert "distance" in hits[0]


def test_delete_by_session_clears_fts():
  store, _ = _make_store("del_session")
  store.add_chunks([
    _chunk("a", "x", session_id="s1"),
    _chunk("b", "y", session_id="s2"),
  ])
  removed = store.delete_by_session("s1")
  assert removed == 1
  assert store.fts.count() == 1


def test_delete_by_project_clears_fts():
  store, _ = _make_store("del_project")
  store.add_chunks([
    _chunk("a", "x", project="proj-a"),
    _chunk("b", "y", project="proj-b"),
  ])
  store.delete_by_project("proj-a")
  assert store.fts.count() == 1


def test_delete_all_clears_fts():
  store, _ = _make_store("del_all")
  store.add_chunks([_chunk("a", "x"), _chunk("b", "y")])
  store.delete_all()
  assert store.fts.count() == 0


def test_lazy_migration_backfills_fts_from_chroma():
  """Simulate an upgrade from <0.9: Chroma has chunks, FTS is empty."""
  tmpdir = tempfile.mkdtemp()
  store = VaultStore(persist_dir=Path(tmpdir), collection_name="migrate")
  store.add_chunks([_chunk("a", "hello world"), _chunk("b", "another")])
  # Wipe the FTS index to mimic pre-0.9 data.
  store.fts.delete_all()
  assert store.fts.count() == 0
  # Reset migration latch (would normally happen on a fresh process).
  store._migration_checked = False

  hits = store.search("hello", top_k=5, mode="hybrid")
  assert store.fts.count() == 2
  assert any(h["id"] == "a" for h in hits)


def test_migration_runs_only_once_per_instance():
  store, _ = _make_store("migrate_once")
  store.add_chunks([_chunk("a", "x")])
  store._migration_checked = False
  store._ensure_fts_migrated()
  assert store._migration_checked is True
  # Second call is a no-op.
  store._ensure_fts_migrated()
  assert store._migration_checked is True


def test_hybrid_default_mode():
  """search() with no explicit mode should be hybrid."""
  store, _ = _make_store("default_mode")
  store.add_chunks([_chunk("a", "useAuthProvider hook")])
  hits = store.search("useAuthProvider", top_k=3)
  assert hits and "score" in hits[0]


def test_hybrid_respects_semantic_weight_extreme():
  """semantic_weight=0 should match keyword-only ordering."""
  store, _ = _make_store("weights")
  store.add_chunks([
    _chunk("1", "useAuthProvider useAuthProvider useAuthProvider"),
    _chunk("2", "barely a useAuthProvider mention"),
  ])
  hits = store.search(
    "useAuthProvider", top_k=2, mode="hybrid", semantic_weight=0.0,
  )
  assert hits[0]["id"] == "1"


def test_fts_path_lives_under_persist_dir():
  store, tmpdir = _make_store("fts_path")
  assert isinstance(store.fts, FTSIndex)
  assert store.fts.db_path == Path(tmpdir) / "fts.sqlite"
  assert store.fts.db_path.exists()
