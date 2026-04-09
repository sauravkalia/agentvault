"""Configuration management for AgentVault."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

DEFAULT_VAULT_DIR = Path.home() / ".agentvault"
DEFAULT_CHROMADB_DIR = DEFAULT_VAULT_DIR / "chromadb"
DEFAULT_COLLECTION_NAME = "agentvault_chunks"
DEFAULT_CONFIG_PATH = DEFAULT_VAULT_DIR / "config.json"


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


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
  config_path = path or DEFAULT_CONFIG_PATH
  defaults = get_default_config()

  if config_path.exists():
    with open(config_path) as f:
      user_config = json.load(f)
    defaults.update(user_config)

  return defaults


def save_config(config: dict[str, Any], path: Optional[Path] = None) -> Path:
  config_path = path or DEFAULT_CONFIG_PATH
  config_path.parent.mkdir(parents=True, exist_ok=True)

  with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

  return config_path
