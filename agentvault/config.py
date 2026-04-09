"""Configuration management for AgentVault."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

DEFAULT_VAULT_DIR = Path.home() / ".agentvault"
DEFAULT_CHROMADB_DIR = DEFAULT_VAULT_DIR / "chromadb"
DEFAULT_COLLECTION_NAME = "agentvault_chunks"
DEFAULT_CONFIG_PATH = DEFAULT_VAULT_DIR / "config.json"

# Allowed keys and their expected types for validation
ALLOWED_CONFIG_KEYS = {
  "vault_dir": str,
  "chromadb_dir": str,
  "collection_name": str,
  "obsidian_vault": (str, type(None)),
  "adapters": dict,
  "auto_sync": bool,
  "chunk_max_tokens": int,
}


def get_default_config() -> dict[str, Any]:
  return {
    "vault_dir": str(DEFAULT_VAULT_DIR),
    "chromadb_dir": str(DEFAULT_CHROMADB_DIR),
    "collection_name": DEFAULT_COLLECTION_NAME,
    "obsidian_vault": None,
    "adapters": {
      "claude-code": {"enabled": True, "history_path": str(Path.home() / ".claude" / "projects")},
      "opencode": {"enabled": True, "history_path": str(Path.home() / ".opencode")},
      "cursor": {"enabled": True, "history_path": None},
      "chatgpt": {"enabled": False, "history_path": None},
      "codex": {"enabled": True, "history_path": None},
    },
    "auto_sync": False,
    "chunk_max_tokens": 800,
  }


def _validate_config(config: dict[str, Any]) -> dict[str, Any]:
  """Validate config values — reject unexpected keys and wrong types."""
  validated = {}
  defaults = get_default_config()

  for key, value in config.items():
    # Skip unknown keys
    if key not in ALLOWED_CONFIG_KEYS:
      continue

    expected_type = ALLOWED_CONFIG_KEYS[key]
    if isinstance(expected_type, tuple):
      if not isinstance(value, expected_type):
        validated[key] = defaults.get(key)
        continue
    elif not isinstance(value, expected_type):
      validated[key] = defaults.get(key)
      continue

    # Validate path values don't contain traversal
    if key in ("vault_dir", "chromadb_dir", "obsidian_vault") and isinstance(value, str):
      resolved = Path(value).expanduser().resolve()
      # Ensure it's under home or an absolute path (no relative shenanigans)
      if ".." in Path(value).parts:
        validated[key] = defaults.get(key)
        continue

    validated[key] = value

  return validated


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
  config_path = path or DEFAULT_CONFIG_PATH
  defaults = get_default_config()

  if config_path.exists():
    with open(config_path) as f:
      user_config = json.load(f)
    validated = _validate_config(user_config)
    defaults.update(validated)

  return defaults


def save_config(config: dict[str, Any], path: Optional[Path] = None) -> Path:
  """Save config atomically with restrictive permissions."""
  config_path = path or DEFAULT_CONFIG_PATH
  config_path.parent.mkdir(parents=True, exist_ok=True)

  # Atomic write
  fd, tmp_path = tempfile.mkstemp(
    dir=str(config_path.parent),
    suffix=".json",
    prefix=".config_tmp_",
  )
  try:
    with os.fdopen(fd, "w") as f:
      json.dump(config, f, indent=2)
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, str(config_path))
  except Exception:
    try:
      os.unlink(tmp_path)
    except OSError:
      pass
    raise

  return config_path
