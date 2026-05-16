"""Best-effort local injection log for the UserPromptSubmit hook.

Appends one JSON object per line to `~/.agentvault/injection_log.jsonl`
when context is injected, so a future `agentvault tune` command can
calibrate the relevance threshold against real usage. PII-light: the
prompt itself is recorded only as a SHA-1 prefix, never as plaintext.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Iterable

_MAX_LINES = 1000  # cap so the log never grows unboundedly


def _prompt_hash(prompt: str) -> str:
  return hashlib.sha1(prompt.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _prune(path: Path, keep: int = _MAX_LINES) -> None:
  """Rewrite the log keeping only the most recent `keep` lines. Silent
  on any IO error — the log is a best-effort feature, never load-bearing.
  """
  try:
    if not path.exists():
      return
    if path.stat().st_size < 256 * 1024:
      return
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if len(lines) <= keep:
      return
    trimmed = "\n".join(lines[-keep:]) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(trimmed, encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
  except OSError:
    pass


def record_injection(
  path: Path,
  *,
  prompt: str,
  project: str | None,
  session_id: str | None,
  chunk_ids: Iterable[str],
  now: float | None = None,
) -> None:
  """Append one record for a UserPromptSubmit injection. Fails open."""
  try:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
      "ts": now if now is not None else time.time(),
      "prompt_hash": _prompt_hash(prompt or ""),
      "project": project or "",
      "session_id": session_id or "",
      "chunk_ids": list(chunk_ids),
    }
    line = json.dumps(record, separators=(",", ":"))
    with open(path, "a", encoding="utf-8") as f:
      f.write(line + "\n")
    try:
      os.chmod(path, 0o600)
    except OSError:
      pass
    _prune(path)
  except OSError:
    pass


def read_log(path: Path) -> list[dict]:
  """Return all records in the log (best effort, skips malformed lines)."""
  if not path.exists():
    return []
  out: list[dict] = []
  try:
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
      raw = raw.strip()
      if not raw:
        continue
      try:
        out.append(json.loads(raw))
      except json.JSONDecodeError:
        continue
  except OSError:
    return []
  return out
