"""SQLite FTS5 keyword index for AgentVault Memory.

Sits alongside ChromaDB to give exact-string recall (function names, error
codes, file paths) that vector search misses. VaultStore writes to both
stores in `add_chunks` and queries both in hybrid mode.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

# Columns kept UNINDEXED so they're stored but don't influence BM25 ranking.
# `content` is the only ranked column.
_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
  id UNINDEXED,
  content,
  project UNINDEXED,
  source UNINDEXED,
  git_branch UNINDEXED,
  session_id UNINDEXED,
  timestamp UNINDEXED,
  chunk_index UNINDEXED,
  tokenize = 'unicode61 remove_diacritics 2'
);
"""


def _escape_fts_query(q: str) -> str:
  """Escape a user query for FTS5 MATCH.

  FTS5 reserves characters like `"`, `(`, `)`, `:`, `*`, `-`, `^`, `.`.
  We wrap each whitespace-split term in double quotes and double any internal
  quotes — this turns the query into a conjunctive phrase search of literal
  tokens, which is what users intuitively expect when they type a function
  name or error code.
  """
  terms = [t for t in q.split() if t]
  if not terms:
    return ""
  quoted = []
  for t in terms:
    t = t.replace('"', '""')
    quoted.append(f'"{t}"')
  return " ".join(quoted)


class FTSIndex:
  """Manages a SQLite FTS5 table for keyword search over chunk content."""

  def __init__(self, db_path: Path):
    self.db_path = Path(db_path)
    self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    self.conn = sqlite3.connect(str(self.db_path))
    self.conn.execute("PRAGMA journal_mode=WAL")
    self.conn.execute("PRAGMA synchronous=NORMAL")
    self.conn.executescript(_SCHEMA)
    self.conn.commit()
    # Restrict permissions on the db file itself
    try:
      self.db_path.chmod(0o600)
    except OSError:
      pass

  def add(self, rows: Iterable[dict]) -> int:
    """Insert rows. Each row dict must have keys: id, content, project,
    source, git_branch, session_id, timestamp, chunk_index.

    Re-inserting the same id appends a duplicate; callers should delete
    by id first if they want replace semantics. VaultStore.add_chunks
    already filters out existing ids before writing.
    """
    rows = list(rows)
    if not rows:
      return 0
    self.conn.executemany(
      "INSERT INTO chunks(id, content, project, source, git_branch, "
      "session_id, timestamp, chunk_index) "
      "VALUES (:id, :content, :project, :source, :git_branch, "
      ":session_id, :timestamp, :chunk_index)",
      rows,
    )
    self.conn.commit()
    return len(rows)

  def delete_by_ids(self, ids: list[str]) -> int:
    if not ids:
      return 0
    placeholders = ",".join("?" * len(ids))
    cur = self.conn.execute(
      f"DELETE FROM chunks WHERE id IN ({placeholders})", ids
    )
    self.conn.commit()
    return cur.rowcount or 0

  def delete_where(self, **filters: str) -> int:
    if not filters:
      return 0
    where = " AND ".join(f"{k} = ?" for k in filters)
    cur = self.conn.execute(
      f"DELETE FROM chunks WHERE {where}", tuple(filters.values())
    )
    self.conn.commit()
    return cur.rowcount or 0

  def delete_all(self) -> int:
    cur = self.conn.execute("DELETE FROM chunks")
    self.conn.commit()
    return cur.rowcount or 0

  def count(self) -> int:
    cur = self.conn.execute("SELECT count(*) FROM chunks")
    return cur.fetchone()[0]

  def existing_ids(self) -> set[str]:
    cur = self.conn.execute("SELECT id FROM chunks")
    return {row[0] for row in cur.fetchall()}

  def search(
    self,
    query: str,
    top_k: int = 10,
    project: Optional[str] = None,
    source: Optional[str] = None,
    git_branch: Optional[str] = None,
  ) -> list[dict]:
    """Keyword search ranked by BM25 (lower = better).

    Returns a list of hits with the same shape as VaultStore.search results:
      {id, content, metadata, bm25}
    where `bm25` is the raw BM25 score (more negative = better).
    """
    match = _escape_fts_query(query)
    if not match:
      return []

    sql = (
      "SELECT id, content, project, source, git_branch, session_id, "
      "timestamp, chunk_index, bm25(chunks) AS score "
      "FROM chunks WHERE chunks MATCH ?"
    )
    params: list = [match]
    if project:
      sql += " AND project = ?"
      params.append(project)
    if source:
      sql += " AND source = ?"
      params.append(source)
    if git_branch:
      sql += " AND git_branch = ?"
      params.append(git_branch)
    sql += " ORDER BY score LIMIT ?"
    params.append(top_k)

    try:
      cur = self.conn.execute(sql, params)
    except sqlite3.OperationalError:
      # Malformed query after escaping (rare). Treat as no results.
      return []

    hits = []
    for row in cur.fetchall():
      (
        cid, content, proj, src, branch, session_id, ts, idx, score,
      ) = row
      hits.append({
        "id": cid,
        "content": content,
        "metadata": {
          "project": proj,
          "source": src,
          "git_branch": branch,
          "session_id": session_id,
          "timestamp": ts,
          "chunk_index": idx,
        },
        "bm25": score,
      })
    return hits

  def close(self) -> None:
    self.conn.close()
