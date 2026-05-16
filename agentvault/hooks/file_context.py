"""Helper for the PreToolUse `file-context` hook.

When Claude is about to Read / Edit / Write a file, this surfaces what
was previously discussed about that file in past AI sessions. Kept as a
pure helper so it's testable without spinning up the full CLI.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

# Defaults tuned for "don't be annoying" — these are small on purpose.
MAX_RESULTS = 3
MIN_RELEVANCE = 0.30
SNIPPET_LEN = 200
THROTTLE_SECONDS = 60.0
THROTTLE_MAX_ENTRIES = 200


def _basename_query(file_path: str) -> str:
  """Pick the most discriminating token for vault search.

  Full paths tokenize awkwardly (FTS5 strips `/` and `.`), and most past
  discussions reference files by their short name. So we search by
  basename — `src/auth/jwt.py` → `jwt.py`. The hybrid search in v0.9.0
  then matches BM25 on this token + semantic on the prose context.
  """
  base = os.path.basename(file_path.rstrip("/")) or file_path
  return base


def _load_throttle(path: Path) -> dict[str, float]:
  if not path.exists():
    return {}
  try:
    with open(path) as f:
      data = json.load(f)
    return {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}
  except (OSError, json.JSONDecodeError, ValueError, TypeError):
    return {}


def _save_throttle(path: Path, data: dict[str, float]) -> None:
  """Atomic write with restrictive perms. Best-effort — never raises."""
  try:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
      dir=str(path.parent), suffix=".json", prefix=".throttle_tmp_",
    )
    with os.fdopen(fd, "w") as f:
      json.dump(data, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, str(path))
  except OSError:
    pass


def _prune_throttle(data: dict[str, float], now: float) -> dict[str, float]:
  """Keep the throttle file from growing without bound — drop entries
  older than the window, then cap remaining entries to the N most recent.
  """
  fresh = {k: v for k, v in data.items() if now - v < THROTTLE_SECONDS * 4}
  if len(fresh) > THROTTLE_MAX_ENTRIES:
    items = sorted(fresh.items(), key=lambda kv: -kv[1])[:THROTTLE_MAX_ENTRIES]
    fresh = dict(items)
  return fresh


def _format_block(file_path: str, hits: list[dict]) -> str:
  """Render the markdown block injected into Claude's context."""
  lines = [f"## Past discussion of `{file_path}`"]
  for h in hits:
    meta = h.get("metadata") or {}
    proj = meta.get("project", "?")
    src = meta.get("source", "?")
    ts = (meta.get("timestamp") or "")[:10]
    snippet = (h.get("content") or "").replace("\n", " ").strip()
    if len(snippet) > SNIPPET_LEN:
      snippet = snippet[:SNIPPET_LEN] + "…"
    lines.append(f"- [{proj} · {src} · {ts}] {snippet}")
  lines.append(
    "_If a snippet looks relevant, call `vault_search` for full content._"
  )
  return "\n".join(lines)


def build_file_context(
  file_path: str,
  cwd: str,
  store: Any,
  throttle_path: Path,
  *,
  now: Optional[float] = None,
  throttle_seconds: float = THROTTLE_SECONDS,
  max_results: int = MAX_RESULTS,
  min_relevance: float = MIN_RELEVANCE,
) -> Optional[str]:
  """Core logic: produce a markdown block for `file_path`, or None.

  Returns None when:
    - file_path is empty
    - this path was already injected inside the throttle window
    - the vault returned no hits above `min_relevance`

  Side effect: updates the throttle file when a block is produced.
  """
  if not file_path:
    return None

  now = now if now is not None else time.time()
  throttle = _load_throttle(throttle_path)
  last = throttle.get(file_path)
  if last is not None and (now - last) < throttle_seconds:
    return None

  query = _basename_query(file_path)
  project = Path(cwd).name if cwd else None

  try:
    results = store.search(
      query=query,
      top_k=max_results + 2,
      project=project,
      min_relevance=min_relevance,
      mode="hybrid",
    )
  except Exception:
    return None

  results = (results or [])[:max_results]
  if not results:
    return None

  block = _format_block(file_path, results)

  # Mark this path injected and persist (best effort — failure to write
  # the throttle just means we may re-inject sooner than expected).
  throttle[file_path] = now
  throttle = _prune_throttle(throttle, now)
  _save_throttle(throttle_path, throttle)

  return block
