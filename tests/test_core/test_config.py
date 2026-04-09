"""Tests for config validation."""

from agentvault.config import _validate_config, get_default_config


def test_rejects_unknown_keys():
  config = {"vault_dir": "/tmp/test", "evil_key": "payload", "another": 123}
  result = _validate_config(config)
  assert "evil_key" not in result
  assert "another" not in result
  assert "vault_dir" in result


def test_rejects_wrong_types():
  config = {
    "vault_dir": 123,  # should be str
    "auto_sync": "yes",  # should be bool
    "chunk_max_tokens": "large",  # should be int
  }
  defaults = get_default_config()
  result = _validate_config(config)

  # Wrong-typed values should be replaced with defaults
  assert result["vault_dir"] == defaults["vault_dir"]
  assert result["auto_sync"] == defaults["auto_sync"]
  assert result["chunk_max_tokens"] == defaults["chunk_max_tokens"]


def test_rejects_path_traversal():
  config = {"vault_dir": "/tmp/../../../etc/passwd"}
  defaults = get_default_config()
  result = _validate_config(config)
  assert result["vault_dir"] == defaults["vault_dir"]


def test_accepts_valid_config():
  config = {
    "vault_dir": "/Users/test/.agentvault",
    "obsidian_vault": "/Users/test/Documents/Obsidian",
    "auto_sync": True,
    "chunk_max_tokens": 500,
  }
  result = _validate_config(config)
  assert result["vault_dir"] == "/Users/test/.agentvault"
  assert result["obsidian_vault"] == "/Users/test/Documents/Obsidian"
  assert result["auto_sync"] is True
  assert result["chunk_max_tokens"] == 500


def test_none_obsidian_vault_accepted():
  config = {"obsidian_vault": None}
  result = _validate_config(config)
  assert result["obsidian_vault"] is None
