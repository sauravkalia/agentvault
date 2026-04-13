"""ChromaDB writer — chunks sessions and stores them in the vector store."""

from __future__ import annotations

from agentvault.core.ingester import chunk_session
from agentvault.core.schema import AgentSession
from agentvault.core.store import VaultStore
from agentvault.core.summarizer import generate_summary


def ingest_session(
  session: AgentSession,
  store: VaultStore,
  max_tokens: int = 800,
) -> int:
  """Chunk a session and store it in ChromaDB. Returns chunks added."""
  # Generate summary if not already set
  if not session.summary:
    session.summary = generate_summary(session)

  chunks = chunk_session(session, max_tokens=max_tokens)
  return store.add_chunks(chunks)


def ingest_sessions(
  sessions: list[AgentSession],
  store: VaultStore,
  max_tokens: int = 800,
) -> dict:
  """Ingest multiple sessions. Returns summary stats."""
  total_chunks = 0
  total_sessions = 0

  for session in sessions:
    added = ingest_session(session, store, max_tokens=max_tokens)
    if added > 0:
      total_sessions += 1
      total_chunks += added

  return {
    "sessions_ingested": total_sessions,
    "chunks_added": total_chunks,
    "sessions_skipped": len(sessions) - total_sessions,
  }
