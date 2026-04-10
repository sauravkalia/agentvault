"""CLI entry point for AgentVault Memory."""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from agentvault.config import DEFAULT_VAULT_DIR, load_config, save_config

console = Console()


def _atomic_json_write(filepath: Path, data: dict):
  """Write JSON atomically — temp file + rename."""
  import os
  import tempfile

  filepath.parent.mkdir(parents=True, exist_ok=True)
  fd, tmp_path = tempfile.mkstemp(
    dir=str(filepath.parent),
    suffix=".json",
    prefix=".tmp_",
  )
  try:
    with os.fdopen(fd, "w") as f:
      json.dump(data, f, indent=2)
    os.replace(tmp_path, str(filepath))
  except Exception:
    try:
      os.unlink(tmp_path)
    except OSError:
      pass
    raise


def _load_json_with_backup(filepath: Path) -> dict:
  """Load JSON file and create a backup. Returns empty dict if not found."""
  import shutil

  if filepath.exists():
    with open(filepath) as f:
      data = json.load(f)
    backup = filepath.with_suffix(filepath.suffix + ".bak")
    shutil.copy2(str(filepath), str(backup))
    return data
  return {}


def _install_mcp_for_tool(tool_name: str) -> bool:
  """Install AgentVault MCP server for a specific tool. Returns True if installed."""
  import shutil

  python_path = shutil.which("python3") or shutil.which("python") or "python"
  mcp_entry = {
    "command": python_path,
    "args": ["-m", "agentvault.mcp_server"],
  }

  if tool_name == "claude-code":
    config_path = Path.home() / ".claude" / "settings.json"
    if not config_path.parent.exists():
      return False
    settings = _load_json_with_backup(config_path)
    mcp_servers = settings.setdefault("mcpServers", {})
    mcp_servers["agentvault"] = mcp_entry
    _atomic_json_write(config_path, settings)
    return True

  elif tool_name == "cursor":
    config_path = Path.home() / ".cursor" / "mcp.json"
    if not config_path.parent.exists():
      return False
    settings = _load_json_with_backup(config_path)
    mcp_servers = settings.setdefault("mcpServers", {})
    mcp_servers["agentvault"] = mcp_entry
    _atomic_json_write(config_path, settings)
    return True

  elif tool_name == "opencode":
    config_path = Path.home() / ".config" / "opencode" / "opencode.json"
    if not config_path.exists():
      return False
    settings = _load_json_with_backup(config_path)
    mcp_servers = settings.setdefault("mcpServers", {})
    mcp_servers["agentvault"] = {
      "type": "stdio",
      "command": python_path,
      "args": ["-m", "agentvault.mcp_server"],
    }
    _atomic_json_write(config_path, settings)
    return True

  return False


def _get_mcp_supported_tools() -> list[tuple[str, str]]:
  """Return list of (tool_name, config_path) for tools that support MCP."""
  tools = []
  claude = Path.home() / ".claude" / "settings.json"
  if claude.parent.exists():
    tools.append(("claude-code", str(claude)))

  cursor = Path.home() / ".cursor" / "mcp.json"
  if cursor.parent.exists():
    tools.append(("cursor", str(cursor)))

  opencode = Path.home() / ".config" / "opencode" / "opencode.json"
  if opencode.exists():
    tools.append(("opencode", str(opencode)))

  return tools


def _install_auto_save_hook():
  """Install Claude Code Stop hook to auto-ingest after each session."""
  import shutil

  agentvault_cmd = shutil.which("agentvault") or "agentvault"
  claude_settings = Path.home() / ".claude" / "settings.json"

  if not claude_settings.parent.exists():
    return

  settings = _load_json_with_backup(claude_settings)

  hooks = settings.setdefault("hooks", {})
  stop_hooks = hooks.setdefault("Stop", [])

  # Check if already installed
  for hook_entry in stop_hooks:
    hook_list = hook_entry.get("hooks", [])
    for h in hook_list:
      if "agentvault" in h.get("command", ""):
        return  # Already installed

  stop_hooks.append({
    "matcher": "",
    "hooks": [{
      "type": "command",
      "command": f"{agentvault_cmd} ingest --source claude-code",
    }],
  })

  _atomic_json_write(claude_settings, settings)


@click.group()
@click.version_option(package_name="agentvault-memory")
def cli():
  """AgentVault Memory — Unified memory for AI coding agents."""
  pass


@cli.command()
@click.option("--obsidian", type=click.Path(), default=None, help="Path to your Obsidian vault")
def init(obsidian: str | None):
  """Initialize AgentVault and auto-detect AI tools."""
  from agentvault.adapters.claude_code import ClaudeCodeAdapter
  from agentvault.adapters.codex import CodexAdapter
  from agentvault.adapters.cursor import CursorAdapter
  from agentvault.adapters.opencode import OpenCodeAdapter

  console.print("\n[bold]AgentVault Memory Init[/bold]\n")

  # Create vault directory with restrictive permissions
  DEFAULT_VAULT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
  DEFAULT_VAULT_DIR.chmod(0o700)
  console.print(f"  Vault directory: {DEFAULT_VAULT_DIR}")

  # Auto-detect tools
  adapters = [
    ClaudeCodeAdapter(),
    OpenCodeAdapter(),
    CodexAdapter(),
    CursorAdapter(),
  ]

  console.print("\n  [bold]Detecting AI tools:[/bold]")
  for adapter in adapters:
    if adapter.detect():
      sessions = adapter.discover_sessions()
      console.print(f"    [green]\u2713[/green] {adapter.name}: {len(sessions)} sessions found")
    else:
      console.print(f"    [dim]\u2717 {adapter.name}: not found[/dim]")

  # Obsidian — auto-detect if not provided
  if not obsidian:
    common_paths = [
      Path.home() / "Documents" / "ObsidianVault",
      Path.home() / "Documents" / "Obsidian",
      Path.home() / "Documents" / "Obsidian Vault",
      Path.home() / "ObsidianVault",
      Path.home() / "Obsidian",
    ]
    for candidate in common_paths:
      if (candidate / ".obsidian").exists():
        obsidian = str(candidate)
        break

  console.print("\n  [bold]Obsidian:[/bold]")
  if obsidian:
    obsidian_path = Path(obsidian).expanduser().resolve()
    if obsidian_path.exists():
      console.print(f"    [green]\u2713[/green] Vault found: {obsidian_path}")
    else:
      console.print(f"    [yellow]![/yellow] Path doesn't exist: {obsidian_path}")
      obsidian = None
  if not obsidian:
    console.print("    [dim]\u2717 Not found (optional)[/dim]")
    console.print("    [dim]  Add manually with: agentvault init --obsidian ~/path/to/vault[/dim]")

  # Save config
  config = load_config()
  if obsidian:
    config["obsidian_vault"] = str(Path(obsidian).expanduser().resolve())
  save_config(config)

  console.print(f"\n  Config saved to: {DEFAULT_VAULT_DIR / 'config.json'}")

  # Auto-install MCP server for all detected tools
  console.print("\n  [bold]MCP Server:[/bold]")
  mcp_tools = _get_mcp_supported_tools()
  if mcp_tools:
    for tool_name, config_path in mcp_tools:
      try:
        _install_mcp_for_tool(tool_name)
        console.print(f"    [green]\u2713[/green] {tool_name}")
      except Exception as e:
        console.print(f"    [yellow]![/yellow] {tool_name}: {e}")
  else:
    console.print("    [dim]\u2717 No MCP-compatible tools found[/dim]")
    console.print("    [dim]  Run manually with: agentvault mcp-install[/dim]")

  # Auto-install auto-save hook
  console.print("\n  [bold]Auto-Save Hook:[/bold]")
  try:
    _install_auto_save_hook()
    console.print(
      "    [green]\u2713[/green] Installed — new sessions "
      "will be ingested automatically"
    )
  except Exception as e:
    console.print(f"    [yellow]![/yellow] Could not install: {e}")

  console.print("\n  Run [bold]agentvault ingest[/bold] to import your history.\n")


@cli.command()
@click.option("--source", type=str, default=None, help="Only ingest from specific source")
@click.option("--max-tokens", type=int, default=800, help="Max tokens per chunk")
def ingest(source: str | None, max_tokens: int):
  """Ingest conversation history from detected AI tools."""
  from agentvault.adapters.claude_code import ClaudeCodeAdapter
  from agentvault.adapters.codex import CodexAdapter
  from agentvault.adapters.cursor import CursorAdapter
  from agentvault.adapters.opencode import OpenCodeAdapter
  from agentvault.core.store import VaultStore
  from agentvault.writers.chromadb_writer import ingest_sessions
  from agentvault.writers.obsidian import write_daily_digest, write_session

  config = load_config()
  store = VaultStore()

  adapters = [
    ClaudeCodeAdapter(),
    OpenCodeAdapter(),
    CodexAdapter(),
    CursorAdapter(),
  ]
  if source:
    adapters = [a for a in adapters if a.name == source]

  console.print("\n[bold]AgentVault Memory Ingest[/bold]\n")

  all_sessions = []

  for adapter in adapters:
    if not adapter.detect():
      console.print(f"  [dim]{adapter.name}: not found, skipping[/dim]")
      continue

    console.print(f"  [bold]{adapter.name}[/bold]")
    sessions = adapter.get_all_sessions()
    console.print(f"    Parsed {len(sessions)} sessions")

    all_sessions.extend(sessions)

  if not all_sessions:
    console.print("\n  No sessions found. Nothing to ingest.\n")
    return

  # Write to ChromaDB
  console.print("\n  Writing to ChromaDB...")
  result = ingest_sessions(all_sessions, store, max_tokens=max_tokens)
  console.print(
    f"    [green]\u2713[/green] {result['chunks_added']} chunks indexed "
    f"({result['sessions_ingested']} sessions, {result['sessions_skipped']} skipped/duplicate)"
  )

  # Write to Obsidian (if configured)
  obsidian_vault = config.get("obsidian_vault")
  if obsidian_vault:
    vault_path = Path(obsidian_vault)
    console.print(f"\n  Writing to Obsidian ({vault_path})...")
    written = 0
    for session in all_sessions:
      try:
        write_session(session, vault_path)
        written += 1
      except Exception as e:
        console.print(f"    [yellow]![/yellow] Failed to write session {session.id[:8]}: {e}")

    # Group by date for daily digests
    by_date: dict[str, list] = {}
    for s in all_sessions:
      date = s.started_at[:10] if s.started_at else "unknown"
      by_date.setdefault(date, []).append(s)

    for date, date_sessions in by_date.items():
      try:
        write_daily_digest(date_sessions, vault_path, date=date)
      except Exception:
        pass

    console.print(f"    [green]\u2713[/green] {written} session files written")

  console.print("\n  [bold green]Done.[/bold green]\n")


@cli.command()
@click.argument("query")
@click.option("--project", "-p", type=str, default=None, help="Filter by project")
@click.option("--source", "-s", type=str, default=None, help="Filter by source tool")
@click.option("--top-k", "-k", type=int, default=5, help="Number of results")
def search(query: str, project: str | None, source: str | None, top_k: int):
  """Search your conversation history."""
  from agentvault.core.store import VaultStore

  store = VaultStore()
  results = store.search(
    query=query,
    top_k=top_k,
    project=project,
    source=source,
  )

  if not results:
    console.print("\nNo results found.\n")
    return

  console.print(f"\n[bold]Found {len(results)} results:[/bold]\n")

  for i, hit in enumerate(results, 1):
    meta = hit["metadata"]
    distance = hit.get("distance")
    relevance = f"{1 - distance:.0%}" if distance is not None else "?"

    console.print(f"[bold]Result {i}[/bold] ({relevance} relevant)")
    console.print(f"  Project: [cyan]{meta.get('project', '?')}[/cyan] | "
                  f"Source: {meta.get('source', '?')} | "
                  f"Branch: {meta.get('git_branch', '?')} | "
                  f"Date: {meta.get('timestamp', '?')[:10]}")
    console.print()

    # Truncate long content for terminal display
    content = hit["content"]
    if len(content) > 500:
      content = content[:500] + "..."
    console.print(f"  {content}")
    console.print()


@cli.command()
def status():
  """Show vault status and statistics."""
  from agentvault.core.store import VaultStore

  config = load_config()

  try:
    store = VaultStore()
    stats = store.get_stats()
  except Exception:
    stats = {"total_chunks": 0, "projects": [], "sources": []}

  table = Table(title="AgentVault Memory Status")
  table.add_column("Metric", style="bold")
  table.add_column("Value")

  table.add_row("Vault directory", str(DEFAULT_VAULT_DIR))
  table.add_row("Total chunks", str(stats["total_chunks"]))
  table.add_row("Projects", ", ".join(stats["projects"]) or "none")
  table.add_row("Sources", ", ".join(stats["sources"]) or "none")
  table.add_row("Obsidian vault", config.get("obsidian_vault") or "not configured")

  console.print()
  console.print(table)
  console.print()


@cli.command(name="mcp-install")
def mcp_install():
  """Install AgentVault MCP server + auto-save hook."""
  console.print("\n  [bold]Installing MCP server:[/bold]")
  mcp_tools = _get_mcp_supported_tools()
  if mcp_tools:
    for tool_name, config_path in mcp_tools:
      try:
        _install_mcp_for_tool(tool_name)
        console.print(f"    [green]\u2713[/green] {tool_name}")
      except Exception as e:
        console.print(f"    [yellow]![/yellow] {tool_name}: {e}")
  else:
    console.print("    [dim]No MCP-compatible tools found[/dim]")

  console.print("\n  [bold]Installing auto-save hook:[/bold]")
  try:
    _install_auto_save_hook()
    console.print("    [green]\u2713[/green] Claude Code stop hook installed")
  except Exception as e:
    console.print(f"    [yellow]![/yellow] {e}")

  console.print("\n  Restart your AI tools to activate.\n")


if __name__ == "__main__":
  cli()
