"""Adapter for Cursor IDE conversation history.

Cursor stores conversations in a SQLite database at:
  ~/Library/Application Support/Cursor/User/globalStorage/state.vscdb

Table: cursorDiskKV
  - composerData:{uuid} keys contain full conversation JSON blobs
  - Two schema versions:
    - Older: 'conversation' array with inline messages
    - Newer (v9+): 'fullConversationHeadersOnly' + empty 'conversationMap'
  - Message types: 1 = user, 2 = assistant
"""

from __future__ import annotations

import json
import platform
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agentvault.adapters.base import BaseAdapter
from agentvault.core.schema import AgentSession, Exchange


def _epoch_ms_to_iso(epoch_ms: int | float | None) -> str:
  """Convert epoch milliseconds to ISO 8601 string."""
  if not epoch_ms:
    return ""
  try:
    dt = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
    return dt.isoformat()
  except (ValueError, OSError):
    return ""


def _extract_message(msg: dict) -> Exchange | None:
  """Extract an Exchange from a Cursor message dict."""
  msg_type = msg.get("type")
  text = msg.get("text", "").strip()

  if not text:
    return None

  if msg_type == 1:
    role = "human"
  elif msg_type == 2:
    role = "assistant"
  else:
    return None

  timestamp = ""
  # Some messages have a timestamp field
  if "timestamp" in msg:
    timestamp = _epoch_ms_to_iso(msg["timestamp"])

  return Exchange(role=role, content=text, timestamp=timestamp)


def _build_workspace_project_map(db_path: Path) -> dict[str, str]:
  """Map composerData keys to project names via workspace storage."""
  ws_dir = db_path.parent.parent / "workspaceStorage"
  if not ws_dir.exists():
    return {}

  project_map: dict[str, str] = {}
  for ws_path in ws_dir.iterdir():
    if not ws_path.is_dir():
      continue
    ws_json = ws_path / "workspace.json"
    ws_db = ws_path / "state.vscdb"
    if not ws_json.exists() or not ws_db.exists():
      continue

    try:
      folder_uri = json.loads(ws_json.read_text()).get("folder", "")
      project_name = Path(folder_uri.replace("file://", "")).name
      if not project_name:
        continue

      conn = sqlite3.connect(f"file:{ws_db}?mode=ro", uri=True)
      rows = conn.execute(
        "SELECT value FROM ItemTable "
        "WHERE key = 'composer.composerData'"
      ).fetchone()
      conn.close()

      if not rows or not rows[0]:
        continue

      data = json.loads(rows[0])
      composers = data.get("allComposers", [])
      for c in composers:
        cid = c.get("composerId", "")
        if cid:
          project_map[cid] = project_name
    except (json.JSONDecodeError, sqlite3.Error, OSError):
      continue

  return project_map


class CursorAdapter(BaseAdapter):
  name = "cursor"
  description = "Cursor IDE conversation history"

  def __init__(self, history_path: Path | None = None):
    # Don't call super().__init__ since Cursor uses a DB file, not a dir
    self.history_path = history_path or self.default_history_path()
    self._db_path = self.history_path
    self._conn: sqlite3.Connection | None = None
    self._project_map: dict[str, str] | None = None

  def default_history_path(self) -> Path:
    system = platform.system()
    if system == "Darwin":
      return (
        Path.home() / "Library" / "Application Support"
        / "Cursor" / "User" / "globalStorage" / "state.vscdb"
      )
    elif system == "Linux":
      return (
        Path.home() / ".config" / "Cursor"
        / "User" / "globalStorage" / "state.vscdb"
      )
    else:
      # Windows
      return (
        Path.home() / "AppData" / "Roaming" / "Cursor"
        / "User" / "globalStorage" / "state.vscdb"
      )

  def detect(self) -> bool:
    return self._db_path.exists() and self._db_path.stat().st_size > 0

  def _get_conn(self) -> sqlite3.Connection:
    if self._conn is None:
      self._conn = sqlite3.connect(
        f"file:{self._db_path}?mode=ro",
        uri=True,
      )
    return self._conn

  def discover_sessions(self) -> list[Path]:
    """Return pseudo-paths for each composerData entry.

    Returns Path objects where the name is the DB key.
    These are passed to parse_session which reads from the DB.
    """
    if not self.detect():
      return []

    try:
      conn = self._get_conn()
      rows = conn.execute(
        "SELECT key FROM cursorDiskKV "
        "WHERE key LIKE 'composerData:%' "
        "AND length(value) > 100 "
        "ORDER BY key"
      ).fetchall()
      # Return pseudo-paths — parse_session will read from DB
      return [Path(row[0]) for row in rows]
    except sqlite3.Error:
      return []

  def parse_session(self, path: Path) -> AgentSession | None:
    """Parse a Cursor conversation from the SQLite database.

    The 'path' is actually a pseudo-path where path.name is the DB key.
    """
    db_key = str(path)

    try:
      conn = self._get_conn()
      row = conn.execute(
        "SELECT value FROM cursorDiskKV WHERE key = ?",
        (db_key,),
      ).fetchone()
    except sqlite3.Error:
      return None

    if not row or not row[0]:
      return None

    try:
      data = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
      return None

    composer_id = data.get("composerId", "")
    name = data.get("name", "")
    created_at = _epoch_ms_to_iso(data.get("createdAt"))
    updated_at = _epoch_ms_to_iso(data.get("lastUpdatedAt"))

    # Extract messages — handle both schema versions
    messages = data.get("conversation", [])
    if not messages:
      # Newer schema: headers only, no inline content
      # We can still get bubble text if available
      headers = data.get("fullConversationHeadersOnly", [])
      if not headers:
        return None
      # Headers don't contain text — skip these sessions
      return None

    exchanges: list[Exchange] = []
    for msg in messages:
      if not isinstance(msg, dict):
        continue
      exchange = _extract_message(msg)
      if exchange:
        exchanges.append(exchange)

    if not exchanges:
      return None

    # Detect project — try workspace map first, then context
    if self._project_map is None:
      self._project_map = _build_workspace_project_map(self._db_path)

    project = self._project_map.get(composer_id, "")

    if not project:
      context = data.get("context", {})
      if isinstance(context, dict):
        composers = context.get("composers", [])
        if composers and isinstance(composers, list):
          for c in composers:
            if isinstance(c, dict) and "uri" in c:
              uri = c["uri"]
              if "/" in uri:
                project = Path(uri).name
                break

    if not project:
      project = "cursor"

    model_name = ""
    model_config = data.get("modelConfig", {})
    if isinstance(model_config, dict):
      model_name = model_config.get("modelName", "")

    return AgentSession(
      id=composer_id,
      source="cursor",
      project=project,
      started_at=created_at,
      ended_at=updated_at or created_at,
      working_directory="",
      exchanges=exchanges,
      summary=name or None,
      metadata={
        "composer_id": composer_id,
        "model": model_name,
        "schema_version": data.get("_v", "unknown"),
      },
    )

  def get_all_sessions(self, since_mtime: float | None = None) -> list[AgentSession]:
    """Override to ensure DB connection is closed after use."""
    try:
      return super().get_all_sessions(since_mtime=since_mtime)
    finally:
      if self._conn:
        self._conn.close()
        self._conn = None
