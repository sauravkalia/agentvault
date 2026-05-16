"""Tests for the SQLite FTS5 keyword index."""

import tempfile
from pathlib import Path

from agentvault.core.fts_index import FTSIndex, _escape_fts_query


def _make_index():
  tmpdir = tempfile.mkdtemp()
  return FTSIndex(Path(tmpdir) / "fts.sqlite")


def _row(cid: str, content: str, **overrides):
  base = {
    "id": cid,
    "content": content,
    "project": "proj-a",
    "source": "claude-code",
    "git_branch": "main",
    "session_id": "s1",
    "timestamp": "2026-05-01T00:00:00Z",
    "chunk_index": 0,
  }
  base.update(overrides)
  return base


def test_add_and_count():
  fts = _make_index()
  fts.add([_row("a", "hello world"), _row("b", "another chunk")])
  assert fts.count() == 2


def test_keyword_exact_match():
  fts = _make_index()
  fts.add([
    _row("1", "we should use useAuthProvider for the new flow"),
    _row("2", "completely unrelated content about pasta recipes"),
  ])
  hits = fts.search("useAuthProvider", top_k=5)
  assert len(hits) == 1
  assert hits[0]["id"] == "1"


def test_filter_by_project():
  fts = _make_index()
  fts.add([
    _row("1", "auth flow refactor", project="proj-a"),
    _row("2", "auth flow refactor", project="proj-b"),
  ])
  hits = fts.search("auth", top_k=5, project="proj-b")
  assert len(hits) == 1
  assert hits[0]["id"] == "2"


def test_bm25_ranks_more_relevant_first():
  fts = _make_index()
  fts.add([
    _row("dense", "redirect redirect redirect undefined redirect"),
    _row("sparse", "we briefly mentioned a redirect once"),
  ])
  hits = fts.search("redirect", top_k=5)
  assert hits[0]["id"] == "dense"


def test_delete_by_ids():
  fts = _make_index()
  fts.add([_row("a", "alpha"), _row("b", "beta")])
  removed = fts.delete_by_ids(["a"])
  assert removed == 1
  assert fts.count() == 1


def test_delete_where():
  fts = _make_index()
  fts.add([
    _row("a", "alpha", session_id="s1"),
    _row("b", "beta", session_id="s2"),
  ])
  removed = fts.delete_where(session_id="s1")
  assert removed == 1
  assert fts.count() == 1


def test_empty_query_returns_no_results():
  fts = _make_index()
  fts.add([_row("a", "anything")])
  assert fts.search("   ", top_k=5) == []


def test_quotes_in_query_dont_break():
  fts = _make_index()
  fts.add([_row("a", 'he said "hello there" yesterday')])
  # User typing a stray quote should not raise — escaping handles it.
  hits = fts.search('hello "there', top_k=5)
  assert isinstance(hits, list)


def test_existing_ids_returns_set():
  fts = _make_index()
  fts.add([_row("a", "x"), _row("b", "y")])
  assert fts.existing_ids() == {"a", "b"}


def test_escape_query_quotes_terms():
  out = _escape_fts_query("useAuthProvider login")
  assert out == '"useAuthProvider" "login"'


def test_escape_doubles_internal_quotes():
  out = _escape_fts_query('weird"term')
  assert out == '"weird""term"'
