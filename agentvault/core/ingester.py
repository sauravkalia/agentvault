"""Ingestion engine — chunks sessions and prepares them for storage."""

from __future__ import annotations

import hashlib
from typing import Optional

from agentvault.core.schema import AgentSession, Chunk, Exchange


def _estimate_tokens(text: str) -> int:
  """Rough token estimate — 1 token per ~4 chars. Good enough for chunking."""
  return len(text) // 4


def _build_exchange_text(exchange: Exchange) -> str:
  """Format a single exchange as readable text."""
  role_label = {"human": "User", "assistant": "Assistant", "system": "System"}.get(
    exchange.role, exchange.role.capitalize()
  )
  text = f"**{role_label}**: {exchange.content}"

  if exchange.tool_calls:
    tools_used = [tc.name for tc in exchange.tool_calls]
    text += f"\n[Tools used: {', '.join(tools_used)}]"

  return text


def chunk_session(
  session: AgentSession,
  max_tokens: int = 800,
) -> list[Chunk]:
  """Split a session into chunks suitable for embedding.

  Groups exchanges into pairs (human + assistant) and accumulates
  until hitting the token limit, then starts a new chunk.
  """
  if not session.exchanges:
    return []

  chunks: list[Chunk] = []
  current_texts: list[str] = []
  current_tokens = 0
  chunk_index = 0

  # Add session header to first chunk
  header = f"[{session.source}] Project: {session.project}"
  if session.git_branch:
    header += f" | Branch: {session.git_branch}"
  header += f" | {session.started_at}"

  for exchange in session.exchanges:
    if exchange.role == "system":
      continue

    text = _build_exchange_text(exchange)
    tokens = _estimate_tokens(text)

    # If adding this exchange exceeds limit, flush current chunk
    if current_texts and (current_tokens + tokens) > max_tokens:
      chunk_content = f"{header}\n\n" + "\n\n".join(current_texts) if chunk_index == 0 else "\n\n".join(current_texts)
      chunk_id = _make_chunk_id(session.id, chunk_index)

      chunks.append(Chunk(
        id=chunk_id,
        session_id=session.id,
        source=session.source,
        project=session.project,
        content=chunk_content,
        timestamp=exchange.timestamp or session.started_at,
        git_branch=session.git_branch,
        chunk_index=chunk_index,
      ))
      current_texts = []
      current_tokens = 0
      chunk_index += 1

    current_texts.append(text)
    current_tokens += tokens

  # Flush remaining
  if current_texts:
    chunk_content = f"{header}\n\n" + "\n\n".join(current_texts) if chunk_index == 0 else "\n\n".join(current_texts)
    chunk_id = _make_chunk_id(session.id, chunk_index)

    chunks.append(Chunk(
      id=chunk_id,
      session_id=session.id,
      source=session.source,
      project=session.project,
      content=chunk_content,
      timestamp=session.started_at,
      git_branch=session.git_branch,
      chunk_index=chunk_index,
    ))

  return chunks


def _make_chunk_id(session_id: str, chunk_index: int) -> str:
  raw = f"{session_id}:{chunk_index}"
  return hashlib.sha256(raw.encode()).hexdigest()[:16]
