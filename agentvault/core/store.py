"""ChromaDB + FTS5 storage layer for AgentVault Memory."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Optional

# Suppress ChromaDB telemetry noise
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import chromadb
from chromadb.config import Settings

from agentvault.config import DEFAULT_CHROMADB_DIR, DEFAULT_COLLECTION_NAME
from agentvault.core.fts_index import FTSIndex
from agentvault.core.schema import Chunk


def _age_in_days(timestamp: Optional[str]) -> Optional[float]:
  """Parse an ISO timestamp and return age in days. None on failure."""
  if not timestamp:
    return None
  try:
    from datetime import datetime, timezone
    ts = timestamp.rstrip("Z")
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
      dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = (now - dt).total_seconds() / 86400.0
    return max(delta, 0.0)
  except Exception:
    return None


def _min_max_normalize(values: list[float]) -> list[float]:
  """Min-max normalize to [0, 1]. Identical values all map to 1.0."""
  if not values:
    return []
  lo, hi = min(values), max(values)
  if hi <= lo:
    return [1.0] * len(values)
  span = hi - lo
  return [(v - lo) / span for v in values]


SearchMode = str  # "semantic" | "keyword" | "hybrid"


class VaultStore:
  """Manages ChromaDB + FTS5 storage for conversation chunks."""

  def __init__(
    self,
    persist_dir: Optional[Path] = None,
    collection_name: str = DEFAULT_COLLECTION_NAME,
  ):
    persist_dir = persist_dir or DEFAULT_CHROMADB_DIR
    # Accept either str or Path — convert to Path
    self.persist_dir = Path(persist_dir) if not isinstance(persist_dir, Path) else persist_dir
    self.persist_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Ensure restrictive permissions even if directory already existed
    self.persist_dir.chmod(0o700)

    self.client = chromadb.PersistentClient(
      path=str(self.persist_dir),
      settings=Settings(anonymized_telemetry=False),
    )
    self.collection = self.client.get_or_create_collection(
      name=collection_name,
      metadata={"hnsw:space": "cosine"},
    )

    # FTS5 sits next to the Chroma data so it moves with persist_dir backups.
    self.fts = FTSIndex(self.persist_dir / "fts.sqlite")
    self._migration_checked = False

  # ---------- write path ----------

  def add_chunks(self, chunks: list[Chunk]) -> int:
    """Add chunks to both Chroma and FTS5. Returns count added."""
    if not chunks:
      return 0

    # Deduplicate — skip chunks whose IDs already exist in Chroma
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

    # Mirror into FTS5. Skip ids already present in FTS to stay idempotent
    # across re-runs (e.g., if a previous write crashed between stores).
    fts_existing = self.fts.existing_ids()
    fts_rows = [
      {
        "id": c.id,
        "content": c.content,
        "project": c.project,
        "source": c.source,
        "git_branch": c.git_branch or "",
        "session_id": c.session_id,
        "timestamp": c.timestamp,
        "chunk_index": c.chunk_index,
      }
      for c in new_chunks
      if c.id not in fts_existing
    ]
    if fts_rows:
      self.fts.add(fts_rows)

    return len(new_chunks)

  # ---------- read path ----------

  def search(
    self,
    query: str,
    top_k: int = 5,
    project: Optional[str] = None,
    source: Optional[str] = None,
    git_branch: Optional[str] = None,
    min_relevance: float = 0.0,
    time_decay: bool = False,
    half_life_days: float = 30.0,
    mode: SearchMode = "hybrid",
    semantic_weight: float = 0.5,
  ) -> list[dict]:
    """Search across the vault.

    Args:
      mode: "semantic" (Chroma only), "keyword" (FTS5 BM25 only), or
        "hybrid" (both, normalized + weighted-sum combined).
      semantic_weight: hybrid weight on the semantic side (0..1). The
        keyword side gets (1 - semantic_weight).
      min_relevance: drop semantic results below this cosine relevance.
        Applied to the semantic component only.
      time_decay: re-rank final hits by score * exp(-age_days/half_life).
    """
    if mode in ("keyword", "hybrid"):
      self._ensure_fts_migrated()

    if mode == "semantic":
      hits = self._semantic(
        query, top_k, project, source, git_branch, min_relevance,
      )
    elif mode == "keyword":
      hits = self.fts.search(
        query, top_k=top_k, project=project, source=source,
        git_branch=git_branch,
      )
      for h in hits:
        # Keyword-only hits don't have a Chroma distance; surface a
        # synthetic relevance derived from BM25 rank so downstream
        # formatters that read `distance` still work.
        h["distance"] = None
    elif mode == "hybrid":
      hits = self._hybrid(
        query, top_k, project, source, git_branch,
        min_relevance, semantic_weight,
      )
    else:
      raise ValueError(f"Unknown search mode: {mode}")

    if time_decay:
      for h in hits:
        meta = h.get("metadata", {})
        age = _age_in_days(meta.get("timestamp"))
        base = h.get("score")
        if base is None:
          distance = h.get("distance")
          base = (1 - distance) if distance is not None else 0.5
        if age is not None:
          h["score"] = base * math.exp(-age / half_life_days)
        else:
          h["score"] = base
      hits.sort(key=lambda h: -h.get("score", 0.0))
      hits = hits[:top_k]

    return hits

  def _semantic(
    self,
    query: str,
    top_k: int,
    project: Optional[str],
    source: Optional[str],
    git_branch: Optional[str],
    min_relevance: float,
  ) -> list[dict]:
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
      distance = results["distances"][0][i] if results.get("distances") else None
      if distance is not None and min_relevance > 0:
        relevance = 1 - distance
        if relevance < min_relevance:
          continue
      hits.append({
        "id": results["ids"][0][i],
        "content": results["documents"][0][i],
        "metadata": results["metadatas"][0][i],
        "distance": distance,
      })
    return hits

  def _hybrid(
    self,
    query: str,
    top_k: int,
    project: Optional[str],
    source: Optional[str],
    git_branch: Optional[str],
    min_relevance: float,
    semantic_weight: float,
  ) -> list[dict]:
    """Run both backends, normalize, weighted-sum combine."""
    # Pull a wider candidate pool from each side so a strong hit from one
    # backend isn't dropped just because it didn't make the other side's
    # top-K (we score missing-from-one as 0 on that dimension).
    fetch_k = max(top_k * 3, 10)

    sem = self._semantic(
      query, fetch_k, project, source, git_branch, min_relevance,
    )
    kw = self.fts.search(
      query, top_k=fetch_k, project=project, source=source,
      git_branch=git_branch,
    )

    # Normalize semantic: 1 - distance, then min-max over this query's pool.
    sem_raw = {h["id"]: (1 - h["distance"]) if h["distance"] is not None else 0.5 for h in sem}
    sem_norm_values = _min_max_normalize(list(sem_raw.values()))
    sem_norm = dict(zip(sem_raw.keys(), sem_norm_values))

    # Normalize keyword: BM25 is "lower is better" and signed, so invert.
    # min-max on (-bm25) gives a [0, 1] score.
    kw_raw = {h["id"]: -h["bm25"] for h in kw}
    kw_norm_values = _min_max_normalize(list(kw_raw.values()))
    kw_norm = dict(zip(kw_raw.keys(), kw_norm_values))

    # Index full hit records so we can return content + metadata after merge.
    by_id: dict[str, dict] = {}
    for h in sem:
      by_id[h["id"]] = dict(h)
    for h in kw:
      if h["id"] not in by_id:
        by_id[h["id"]] = {
          "id": h["id"],
          "content": h["content"],
          "metadata": h["metadata"],
          "distance": None,
        }

    kw_weight = 1.0 - semantic_weight
    combined = []
    for cid, hit in by_id.items():
      s = sem_norm.get(cid, 0.0)
      k = kw_norm.get(cid, 0.0)
      hit["score"] = semantic_weight * s + kw_weight * k
      hit["sem_score"] = s
      hit["kw_score"] = k
      combined.append(hit)

    combined.sort(key=lambda h: -h["score"])
    return combined[:top_k]

  # ---------- lazy migration ----------

  def _ensure_fts_migrated(self) -> None:
    """If FTS5 is behind Chroma (e.g., upgraded from <0.9), backfill it.

    Idempotent: only inserts ids that FTS doesn't already have. Runs at
    most once per VaultStore instance.
    """
    if self._migration_checked:
      return
    self._migration_checked = True

    chroma_count = self.collection.count()
    fts_count = self.fts.count()
    if fts_count >= chroma_count:
      return

    # Pull everything from Chroma and add what's missing in FTS.
    existing = self.fts.existing_ids()
    batch_size = 1000
    offset = 0
    while offset < chroma_count:
      page = self.collection.get(
        limit=batch_size,
        offset=offset,
        include=["documents", "metadatas"],
      )
      rows = []
      ids = page.get("ids", [])
      docs = page.get("documents", []) or []
      metas = page.get("metadatas", []) or []
      for i, cid in enumerate(ids):
        if cid in existing:
          continue
        meta = metas[i] if i < len(metas) else {}
        content = docs[i] if i < len(docs) else ""
        rows.append({
          "id": cid,
          "content": content,
          "project": meta.get("project", ""),
          "source": meta.get("source", ""),
          "git_branch": meta.get("git_branch", ""),
          "session_id": meta.get("session_id", ""),
          "timestamp": meta.get("timestamp", ""),
          "chunk_index": meta.get("chunk_index", 0),
        })
      if rows:
        self.fts.add(rows)
      if len(ids) < batch_size:
        break
      offset += batch_size

  # ---------- stats / delete ----------

  def get_stats(self) -> dict:
    """Return store statistics."""
    count = self.collection.count()

    projects: dict[str, int] = {}
    sources: dict[str, int] = {}
    sessions: set[str] = set()
    if count > 0:
      sample = self.collection.get(
        limit=min(count, 10000), include=["metadatas"]
      )
      for meta in sample["metadatas"]:
        proj = meta.get("project", "unknown")
        src = meta.get("source", "unknown")
        projects[proj] = projects.get(proj, 0) + 1
        sources[src] = sources.get(src, 0) + 1
        sessions.add(meta.get("session_id", ""))

    return {
      "total_chunks": count,
      "total_sessions": len(sessions),
      "projects": sorted(projects.keys()),
      "projects_detail": dict(
        sorted(projects.items(), key=lambda x: -x[1])
      ),
      "sources": sorted(sources.keys()),
      "sources_detail": dict(
        sorted(sources.items(), key=lambda x: -x[1])
      ),
    }

  def delete_by_session(self, session_id: str) -> int:
    """Delete all chunks for a session. Returns count deleted."""
    results = self.collection.get(where={"session_id": session_id})
    if results["ids"]:
      self.collection.delete(ids=results["ids"])
      self.fts.delete_by_ids(results["ids"])
    return len(results["ids"])

  def delete_by_project(self, project: str) -> int:
    """Delete all chunks for a project. Returns count deleted."""
    results = self.collection.get(where={"project": project})
    if results["ids"]:
      self.collection.delete(ids=results["ids"])
      self.fts.delete_by_ids(results["ids"])
    return len(results["ids"])

  def delete_by_source(self, source: str) -> int:
    """Delete all chunks for a source tool. Returns count deleted."""
    results = self.collection.get(where={"source": source})
    if results["ids"]:
      self.collection.delete(ids=results["ids"])
      self.fts.delete_by_ids(results["ids"])
    return len(results["ids"])

  def delete_all(self) -> int:
    """Delete all chunks. Returns count deleted."""
    count = self.collection.count()
    if count > 0:
      # Get all IDs and delete
      results = self.collection.get(limit=count)
      if results["ids"]:
        self.collection.delete(ids=results["ids"])
    self.fts.delete_all()
    return count
