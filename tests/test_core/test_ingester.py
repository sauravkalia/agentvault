"""Tests for the ingestion/chunking engine."""

from agentvault.core.ingester import chunk_session
from agentvault.core.schema import AgentSession, Exchange


def _make_session(num_exchanges: int = 4, content_size: int = 100) -> AgentSession:
  """Create a test session with N exchanges."""
  exchanges = []
  for i in range(num_exchanges):
    role = "human" if i % 2 == 0 else "assistant"
    exchanges.append(Exchange(
      role=role,
      content=f"Message {i}: " + "x" * content_size,
      timestamp=f"2026-04-01T10:{i:02d}:00.000Z",
    ))

  return AgentSession(
    id="test-session",
    source="claude-code",
    project="test-project",
    started_at="2026-04-01T10:00:00.000Z",
    ended_at=f"2026-04-01T10:{num_exchanges:02d}:00.000Z",
    working_directory="/test/project",
    exchanges=exchanges,
    git_branch="main",
  )


def test_chunk_session_basic():
  session = _make_session(num_exchanges=4, content_size=50)
  chunks = chunk_session(session, max_tokens=800)

  assert len(chunks) >= 1
  assert all(c.session_id == "test-session" for c in chunks)
  assert all(c.source == "claude-code" for c in chunks)
  assert all(c.project == "test-project" for c in chunks)


def test_chunk_ids_unique():
  session = _make_session(num_exchanges=20, content_size=200)
  chunks = chunk_session(session, max_tokens=300)

  ids = [c.id for c in chunks]
  assert len(ids) == len(set(ids)), "Chunk IDs must be unique"


def test_empty_session():
  session = AgentSession(
    id="empty",
    source="claude-code",
    project="test",
    started_at="",
    ended_at="",
    working_directory="",
    exchanges=[],
  )
  chunks = chunk_session(session)
  assert chunks == []


def test_large_session_creates_multiple_chunks():
  session = _make_session(num_exchanges=20, content_size=500)
  chunks = chunk_session(session, max_tokens=400)

  assert len(chunks) > 1
  # Chunk indices should be sequential
  for i, chunk in enumerate(chunks):
    assert chunk.chunk_index == i


def test_chromadb_metadata():
  session = _make_session(num_exchanges=2)
  chunks = chunk_session(session)

  for chunk in chunks:
    meta = chunk.to_chromadb_metadata()
    assert "session_id" in meta
    assert "source" in meta
    assert "project" in meta
    assert "timestamp" in meta
    # All values must be str/int/float/bool for ChromaDB
    for v in meta.values():
      assert isinstance(v, (str, int, float, bool))
