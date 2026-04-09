"""CLI entry point for AgentVault."""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from agentvault.config import load_config, save_config, DEFAULT_VAULT_DIR

console = Console()


@click.group()
@click.version_option(package_name="agentvault")
def cli():
  """AgentVault — Unified memory for AI coding agents."""
  pass


@cli.command()
@click.option("--obsidian", type=click.Path(), default=None, help="Path to your Obsidian vault")
def init(obsidian: str | None):
  """Initialize AgentVault and auto-detect AI tools."""
  from agentvault.adapters.claude_code import ClaudeCodeAdapter

  console.print("\n[bold]AgentVault Init[/bold]\n")

  # Create vault directory with restrictive permissions
  DEFAULT_VAULT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
  DEFAULT_VAULT_DIR.chmod(0o700)
  console.print(f"  Vault directory: {DEFAULT_VAULT_DIR}")

  # Auto-detect tools
  adapters = [ClaudeCodeAdapter()]

  console.print("\n  [bold]Detecting AI tools:[/bold]")
  for adapter in adapters:
    if adapter.detect():
      sessions = adapter.discover_sessions()
      console.print(f"    [green]\u2713[/green] {adapter.name}: {len(sessions)} sessions found")
    else:
      console.print(f"    [dim]\u2717 {adapter.name}: not found[/dim]")

  # Obsidian
  if obsidian:
    obsidian_path = Path(obsidian).expanduser().resolve()
    if obsidian_path.exists():
      console.print(f"\n  [green]\u2713[/green] Obsidian vault: {obsidian_path}")
    else:
      console.print(f"\n  [yellow]![/yellow] Obsidian path doesn't exist: {obsidian_path}")
      obsidian = None
  else:
    console.print(f"\n  [dim]Obsidian: not configured (optional)[/dim]")
    console.print(f"  [dim]  Add later with: agentvault init --obsidian ~/path/to/vault[/dim]")

  # Save config
  config = load_config()
  if obsidian:
    config["obsidian_vault"] = str(Path(obsidian).expanduser().resolve())
  save_config(config)

  console.print(f"\n  Config saved to: {DEFAULT_VAULT_DIR / 'config.json'}")
  console.print("\n  Run [bold]agentvault ingest[/bold] to import your history.\n")


@cli.command()
@click.option("--source", type=str, default=None, help="Only ingest from specific source")
@click.option("--max-tokens", type=int, default=800, help="Max tokens per chunk")
def ingest(source: str | None, max_tokens: int):
  """Ingest conversation history from detected AI tools."""
  from agentvault.adapters.claude_code import ClaudeCodeAdapter
  from agentvault.core.store import VaultStore
  from agentvault.writers.chromadb_writer import ingest_sessions
  from agentvault.writers.obsidian import write_session, write_daily_digest

  config = load_config()
  store = VaultStore()

  adapters = [ClaudeCodeAdapter()]
  if source:
    adapters = [a for a in adapters if a.name == source]

  console.print("\n[bold]AgentVault Ingest[/bold]\n")

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
  console.print(f"\n  Writing to ChromaDB...")
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

  console.print(f"\n  [bold green]Done.[/bold green]\n")


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

  table = Table(title="AgentVault Status")
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
  """Install AgentVault as an MCP server in Claude Code."""
  import os
  import shutil
  import tempfile

  python_path = shutil.which("python3") or shutil.which("python") or "python"

  console.print(f"\n  Python path: {python_path}")

  # Claude Code settings path
  claude_settings = Path.home() / ".claude" / "settings.json"

  if claude_settings.exists():
    with open(claude_settings) as f:
      settings = json.load(f)
    # Backup existing settings
    backup_path = claude_settings.with_suffix(".json.bak")
    shutil.copy2(str(claude_settings), str(backup_path))
    console.print(f"  Backed up existing settings to {backup_path}")
  else:
    settings = {}

  mcp_servers = settings.setdefault("mcpServers", {})
  mcp_servers["agentvault"] = {
    "command": python_path,
    "args": ["-m", "agentvault.mcp_server"],
  }

  # Atomic write — write to temp file, then rename
  claude_settings.parent.mkdir(parents=True, exist_ok=True)
  fd, tmp_path = tempfile.mkstemp(
    dir=str(claude_settings.parent),
    suffix=".json",
    prefix=".settings_tmp_",
  )
  try:
    with os.fdopen(fd, "w") as f:
      json.dump(settings, f, indent=2)
    os.replace(tmp_path, str(claude_settings))
  except Exception:
    # Clean up temp file on failure
    try:
      os.unlink(tmp_path)
    except OSError:
      pass
    raise

  console.print(f"  [green]\u2713[/green] Added AgentVault MCP server to {claude_settings}")
  console.print("  Restart Claude Code to activate.\n")


if __name__ == "__main__":
  cli()
