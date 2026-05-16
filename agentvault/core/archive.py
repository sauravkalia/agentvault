"""TTL / auto-purge: condense old sessions into a single summary chunk.

Walks the vault, finds sessions whose newest chunk is older than the
configured age, and replaces every chunk for that session with one
short condensed chunk carrying the session's keyword topics and head /
tail snippets. Idempotent: a sentinel chunk id (`<session_id>-archived`)
marks already-archived sessions and is skipped on subsequent runs.

The trade: vector recall on archived sessions drops to one chunk, but
session-level facts ("we worked on X for Y in March") survive and the
store stays small.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from agentvault.core.schema import Chunk
from agentvault.core.summarizer import _extract_keywords

_ARCHIVE_SUFFIX = "-archived"


def _is_archive_chunk(chunk_id: str) -> bool:
  return chunk_id.endswith(_ARCHIVE_SUFFIX)


def _cutoff_iso(older_than_days: int, now: Optional[datetime] = None) -> str:
  """Return the ISO timestamp at the cutoff boundary."""
  now = now or datetime.now(timezone.utc)
  cutoff = now - timedelta(days=older_than_days)
  return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


def _condense(session_id: str, project: str, chunks: list[tuple[str, str, dict]]) -> str:
  """Build the condensed summary content for one archived session."""
  # `chunks` is a list of (id, content, metadata) already sorted by chunk_index.
  if not chunks:
    return f"[ARCHIVED session {session_id}] empty session."

  all_content = "\n".join(c[1] for c in chunks if c[1])
  keywords = _extract_keywords(all_content, top_n=8) if all_content else []

  metas = [c[2] or {} for c in chunks]
  timestamps = sorted({(m.get("timestamp") or "")[:19] for m in metas if m.get("timestamp")})
  span = ""
  if timestamps:
    first = timestamps[0][:10]
    last = timestamps[-1][:10]
    span = f"{first} → {last}" if first != last else first

  head = chunks[0][1] or ""
  tail = chunks[-1][1] or ""
  head_snip = head[:200].replace("\n", " ").strip()
  tail_snip = tail[:200].replace("\n", " ").strip()

  parts = [f"[ARCHIVED session {session_id}] {len(chunks)} chunks"]
  if span:
    parts.append(f", {span}")
  parts.append(f" · project {project or '?'}")
  body_lines = ["".join(parts)]
  if keywords:
    body_lines.append("Topics: " + ", ".join(keywords))
  if head_snip:
    body_lines.append(f"Opened with: {head_snip}…")
  if tail_snip and tail_snip != head_snip:
    body_lines.append(f"Closed with: {tail_snip}…")
  return "\n".join(body_lines)


def archive_old_sessions(
  store: Any,
  *,
  older_than_days: int = 180,
  project: Optional[str] = None,
  dry_run: bool = False,
  now: Optional[datetime] = None,
  chunk_limit: int = 100_000,
) -> dict:
  """Condense old sessions in place.

  Returns a stats dict:
    {
      "sessions_considered": int,
      "sessions_archived": int,
      "sessions_already_archived": int,
      "chunks_removed": int,
      "chunks_added": int,
      "bytes_before": int,
      "bytes_after": int,
    }
  """
  cutoff = _cutoff_iso(older_than_days, now=now)

  where = {"project": project} if project else None
  try:
    page = store.collection.get(
      limit=chunk_limit,
      include=["documents", "metadatas"],
      where=where,
    )
  except Exception:
    return _empty_stats()

  ids = page.get("ids", []) or []
  docs = page.get("documents", []) or []
  metas = page.get("metadatas", []) or []

  # Group by session_id with per-session aggregates.
  by_session: dict[str, dict] = {}
  for i, cid in enumerate(ids):
    meta = metas[i] if i < len(metas) else {}
    sid = meta.get("session_id") or ""
    if not sid:
      continue
    bucket = by_session.setdefault(sid, {
      "chunks": [],
      "min_ts": "",
      "max_ts": "",
      "project": meta.get("project") or "",
      "source": meta.get("source") or "",
      "git_branch": meta.get("git_branch") or "",
      "already_archived": False,
    })
    bucket["chunks"].append((cid, docs[i] if i < len(docs) else "", meta))
    ts = meta.get("timestamp") or ""
    if ts:
      if not bucket["min_ts"] or ts < bucket["min_ts"]:
        bucket["min_ts"] = ts
      if ts > bucket["max_ts"]:
        bucket["max_ts"] = ts
    if _is_archive_chunk(cid):
      bucket["already_archived"] = True

  stats = _empty_stats()
  stats["sessions_considered"] = len(by_session)

  for sid, bucket in by_session.items():
    if bucket["already_archived"]:
      stats["sessions_already_archived"] += 1
      continue
    if not bucket["max_ts"] or bucket["max_ts"] >= cutoff:
      continue

    # Sort chunks by chunk_index for stable head/tail snippets.
    chunks_sorted = sorted(
      bucket["chunks"],
      key=lambda c: (c[2] or {}).get("chunk_index") or 0,
    )

    raw_bytes = sum(len(c[1] or "") for c in chunks_sorted)
    condensed = _condense(sid, bucket["project"], chunks_sorted)
    stats["sessions_archived"] += 1
    stats["chunks_removed"] += len(chunks_sorted)
    stats["chunks_added"] += 1
    stats["bytes_before"] += raw_bytes
    stats["bytes_after"] += len(condensed)

    if dry_run:
      continue

    # Delete first, add second — otherwise delete_by_session would also
    # remove the freshly-added archive chunk.
    try:
      store.delete_by_session(sid)
    except Exception:
      # Skip this session if delete fails; counts still reflect intent.
      continue

    archive_chunk = Chunk(
      id=f"{sid}{_ARCHIVE_SUFFIX}",
      session_id=sid,
      source=bucket["source"],
      project=bucket["project"],
      content=condensed,
      timestamp=bucket["min_ts"] or bucket["max_ts"],
      git_branch=bucket["git_branch"] or None,
      chunk_index=0,
      metadata={"archived": True},
    )
    try:
      store.add_chunks([archive_chunk])
    except Exception:
      pass

  return stats


def _empty_stats() -> dict:
  return {
    "sessions_considered": 0,
    "sessions_archived": 0,
    "sessions_already_archived": 0,
    "chunks_removed": 0,
    "chunks_added": 0,
    "bytes_before": 0,
    "bytes_after": 0,
  }
