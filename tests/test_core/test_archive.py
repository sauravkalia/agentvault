"""Tests for the TTL / archive flow."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentvault.core.archive import (
  _ARCHIVE_SUFFIX,
  _condense,
  _cutoff_iso,
  _is_archive_chunk,
  archive_old_sessions,
)
from agentvault.core.schema import Chunk
from agentvault.core.store import VaultStore


def _store(name: str = "test_archive") -> VaultStore:
  tmpdir = tempfile.mkdtemp()
  return VaultStore(persist_dir=Path(tmpdir), collection_name=name)


def _chunk(cid: str, session: str, content: str, ts: str, *,
          project="proj-a", source="claude-code", idx=0) -> Chunk:
  return Chunk(
    id=cid, session_id=session, source=source, project=project,
    content=content, timestamp=ts, git_branch="main", chunk_index=idx,
  )


def _iso(days_ago: int, *, now: datetime | None = None) -> str:
  now = now or datetime.now(timezone.utc)
  dt = now - timedelta(days=days_ago)
  return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- helpers ----------

def test_is_archive_chunk_detects_suffix():
  assert _is_archive_chunk(f"s1{_ARCHIVE_SUFFIX}")
  assert not _is_archive_chunk("s1-other")


def test_cutoff_iso_format():
  out = _cutoff_iso(30)
  # Must look like an ISO Z timestamp.
  datetime.strptime(out, "%Y-%m-%dT%H:%M:%SZ")


def test_condense_produces_summary_line():
  chunks = [
    ("c1", "First content about jwt auth flow", {"timestamp": "2026-01-01"}),
    ("c2", "Second content about caching", {"timestamp": "2026-01-02"}),
  ]
  out = _condense("sX", "proj-a", chunks)
  assert "[ARCHIVED session sX]" in out
  assert "proj-a" in out
  assert "2 chunks" in out


# ---------- archive flow ----------

def test_archives_old_sessions():
  store = _store("arch_old")
  store.add_chunks([
    _chunk("old-1", "s-old", "discussed auth jwt flow", _iso(200), idx=0),
    _chunk("old-2", "s-old", "decided to use redis cache", _iso(200), idx=1),
    _chunk("new-1", "s-new", "currently working on dashboards", _iso(5), idx=0),
  ])
  stats = archive_old_sessions(store, older_than_days=180)
  assert stats["sessions_archived"] == 1
  assert stats["chunks_removed"] == 2
  assert stats["chunks_added"] == 1
  # FTS5 + Chroma both reflect the replacement.
  assert store.collection.count() == 2  # 1 archive + 1 new untouched
  assert store.fts.count() == 2


def test_skip_sessions_younger_than_cutoff():
  store = _store("arch_recent")
  store.add_chunks([
    _chunk("c1", "s1", "recent work", _iso(30), idx=0),
  ])
  stats = archive_old_sessions(store, older_than_days=180)
  assert stats["sessions_archived"] == 0
  assert store.collection.count() == 1


def test_dry_run_does_not_modify_store():
  store = _store("arch_dry")
  store.add_chunks([
    _chunk("c1", "s-old", "old session content here", _iso(200), idx=0),
    _chunk("c2", "s-old", "more old content", _iso(199), idx=1),
  ])
  before = store.collection.count()
  stats = archive_old_sessions(store, older_than_days=180, dry_run=True)
  assert stats["sessions_archived"] == 1
  assert store.collection.count() == before


def test_archive_is_idempotent():
  store = _store("arch_idemp")
  store.add_chunks([
    _chunk("c1", "s-old", "old auth jwt flow content", _iso(200), idx=0),
    _chunk("c2", "s-old", "old auth refresh content", _iso(199), idx=1),
  ])
  first = archive_old_sessions(store, older_than_days=180)
  assert first["sessions_archived"] == 1
  count_after_first = store.collection.count()

  second = archive_old_sessions(store, older_than_days=180)
  assert second["sessions_archived"] == 0
  assert second["sessions_already_archived"] == 1
  assert store.collection.count() == count_after_first


def test_project_filter_scopes_the_walk():
  store = _store("arch_proj")
  store.add_chunks([
    _chunk("c1", "s-a", "content", _iso(200), project="proj-a"),
    _chunk("c2", "s-b", "content", _iso(200), project="proj-b"),
  ])
  stats = archive_old_sessions(store, older_than_days=180, project="proj-a")
  assert stats["sessions_archived"] == 1
  # proj-b session left untouched.
  metas = store.collection.get(where={"project": "proj-b"})["metadatas"]
  assert len(metas) == 1


def test_archive_chunk_carries_archived_metadata_and_suffix_id():
  store = _store("arch_meta")
  store.add_chunks([
    _chunk("c1", "s-old", "content one", _iso(200)),
    _chunk("c2", "s-old", "content two", _iso(199)),
  ])
  archive_old_sessions(store, older_than_days=180)
  page = store.collection.get(where={"session_id": "s-old"})
  assert len(page["ids"]) == 1
  assert page["ids"][0].endswith(_ARCHIVE_SUFFIX)


def test_bytes_saved_is_positive():
  store = _store("arch_bytes")
  big = "x" * 4000
  store.add_chunks([
    _chunk("c1", "s-old", big, _iso(200), idx=0),
    _chunk("c2", "s-old", big, _iso(199), idx=1),
    _chunk("c3", "s-old", big, _iso(198), idx=2),
  ])
  stats = archive_old_sessions(store, older_than_days=180)
  assert stats["bytes_before"] > stats["bytes_after"]


def test_archive_propagates_to_fts5():
  """Raw chunk content must disappear from the FTS index, replaced by
  the condensed summary so keyword search still surfaces something."""
  store = _store("arch_fts")
  store.add_chunks([
    _chunk("c1", "s-old", "we should retry the upload flow", _iso(200)),
    _chunk("c2", "s-old", "added retry to the upload flow", _iso(199)),
  ])
  archive_old_sessions(store, older_than_days=180)
  # The condensed chunk contains the keyword "upload" via _extract_keywords;
  # the original raw chunks are gone.
  fts_hits = store.fts.search("upload", top_k=10)
  raw_ids = [h["id"] for h in fts_hits]
  assert all(rid.endswith(_ARCHIVE_SUFFIX) for rid in raw_ids)
