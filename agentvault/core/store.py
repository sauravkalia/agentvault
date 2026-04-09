"""ChromaDB storage layer for AgentVault."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# Suppress ChromaDB telemetry noise
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import chromadb
from chromadb.config import Settings

from agentvault.config import DEFAULT_CHROMADB_DIR, DEFAULT_COLLECTION_NAME
from agentvault.core.schema import Chunk


class VaultStore:
  """Manages ChromaDB storage for conversation chunks."""

  def __init__(
    self,
    persist_dir: Optional[Path] = None,
    collection_name: str = DEFAULT_COLLECTION_NAME,
  ):
    self.persist_dir = persist_dir or DEFAULT_CHROMADB_DIR
    self.persist_dir.mkdir(parents=True, exist_ok=True)

    self.client = chromadb.PersistentClient(
      path=str(self.persist_dir),
      settings=Settings(anonymized_telemetry=False),
    )
    self.collection = self.client.get_or_create_collection(
      name=collection_name,
      metadata={"hnsw:space": "cosine"},
    )

  def add_chunks(self, chunks: list[Chunk]) -> int:
    """Add chunks to the store. Returns count of chunks added."""
    if not chunks:
      return 0

    # Deduplicate — skip chunks whose IDs already exist
    existing = set()
    try:
      result = self.collection.get(ids=[c.id for c in chunks])
      existing = set(result["ids"])
    except Exception:
      pass

    new_chunks = [c for c in chunks if c.id not in existing]
    if not new_chunks:
      return 0

    self.collection.add(
      ids=[c.id for c in new_chunks],
      documents=[c.content for c in new_chunks],
      metadatas=[c.to_chromadb_metadata() for c in new_chunks],
    )
    return len(new_chunks)

  def search(
    self,
    query: str,
    top_k: int = 5,
    project: Optional[str] = None,
    source: Optional[str] = None,
    git_branch: Optional[str] = None,
  ) -> list[dict]:
    """Semantic search with optional metadata filters."""
    where_filters = {}
    if project:
      where_filters["project"] = project
    if source:
      where_filters["source"] = source
    if git_branch:
      where_filters["git_branch"] = git_branch

    results = self.collection.query(
      query_texts=[query],
      n_results=top_k,
      where=where_filters if where_filters else None,
    )

    hits = []
    for i in range(len(results["ids"][0])):
      hits.append({
        "id": results["ids"][0][i],
        "content": results["documents"][0][i],
        "metadata": results["metadatas"][0][i],
        "distance": results["distances"][0][i] if results.get("distances") else None,
      })
    return hits

  def get_stats(self) -> dict:
    """Return store statistics."""
    count = self.collection.count()

    projects = set()
    sources = set()
    if count > 0:
      # Sample metadata to get unique values
      sample = self.collection.get(limit=min(count, 1000), include=["metadatas"])
      for meta in sample["metadatas"]:
        projects.add(meta.get("project", "unknown"))
        sources.add(meta.get("source", "unknown"))

    return {
      "total_chunks": count,
      "projects": sorted(projects),
      "sources": sorted(sources),
    }

  def delete_by_session(self, session_id: str) -> int:
    """Delete all chunks for a session. Returns count deleted."""
    results = self.collection.get(where={"session_id": session_id})
    if results["ids"]:
      self.collection.delete(ids=results["ids"])
    return len(results["ids"])
