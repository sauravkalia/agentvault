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


def _install_session_start_hook():
  """Install Claude Code SessionStart hook to auto-inject wake-up context."""
  import shutil

  agentvault_cmd = shutil.which("agentvault") or "agentvault"
  claude_settings = Path.home() / ".claude" / "settings.json"

  if not claude_settings.parent.exists():
    return

  settings = _load_json_with_backup(claude_settings)

  hooks = settings.setdefault("hooks", {})
  start_hooks = hooks.setdefault("SessionStart", [])

  for hook_entry in start_hooks:
    for h in hook_entry.get("hooks", []):
      if "session-start" in h.get("command", ""):
        return  # Already installed

  start_hooks.append({
    "matcher": "",
    "hooks": [{
      "type": "command",
      "command": f"{agentvault_cmd} session-start",
      "timeout": 5000,
    }],
  })

  _atomic_json_write(claude_settings, settings)


def _install_inject_context_hook():
  """Install Claude Code UserPromptSubmit hook for context injection."""
  import shutil

  agentvault_cmd = shutil.which("agentvault") or "agentvault"
  claude_settings = Path.home() / ".claude" / "settings.json"

  if not claude_settings.parent.exists():
    return

  settings = _load_json_with_backup(claude_settings)

  hooks = settings.setdefault("hooks", {})
  submit_hooks = hooks.setdefault("UserPromptSubmit", [])

  for hook_entry in submit_hooks:
    for h in hook_entry.get("hooks", []):
      if "inject-context" in h.get("command", ""):
        return  # Already installed

  submit_hooks.append({
    "matcher": "",
    "hooks": [{
      "type": "command",
      "command": f"{agentvault_cmd} inject-context",
      "timeout": 5000,
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

  # Auto-install context-injection hook
  console.print("\n  [bold]Context-Injection Hook:[/bold]")
  try:
    _install_inject_context_hook()
    console.print(
      "    [green]\u2713[/green] Installed — relevant past context "
      "will be injected before each prompt"
    )
  except Exception as e:
    console.print(f"    [yellow]![/yellow] Could not install: {e}")

  # Auto-install session-start hook
  console.print("\n  [bold]Session-Start Hook:[/bold]")
  try:
    _install_session_start_hook()
    console.print(
      "    [green]\u2713[/green] Installed \u2014 wake-up context "
      "will be injected when sessions start"
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

  # Save last ingest timestamp per source
  import time
  timestamps = config.get("last_ingest_timestamp", {})
  for adapter in adapters:
    if adapter.detect():
      timestamps[adapter.name] = time.time()
  config["last_ingest_timestamp"] = timestamps
  save_config(config)

  console.print("\n  [bold green]Done.[/bold green]\n")


@cli.command()
@click.option("--source", type=str, default=None, help="Only sync specific source")
def sync(source: str | None):
  """Incremental sync — only ingest new sessions since last run."""
  from agentvault.adapters.claude_code import ClaudeCodeAdapter
  from agentvault.adapters.codex import CodexAdapter
  from agentvault.adapters.cursor import CursorAdapter
  from agentvault.adapters.opencode import OpenCodeAdapter
  from agentvault.core.store import VaultStore
  from agentvault.writers.chromadb_writer import ingest_sessions
  from agentvault.writers.obsidian import write_session

  config = load_config()
  store = VaultStore()
  timestamps = config.get("last_ingest_timestamp", {})

  adapters = [
    ClaudeCodeAdapter(),
    OpenCodeAdapter(),
    CodexAdapter(),
    CursorAdapter(),
  ]
  if source:
    adapters = [a for a in adapters if a.name == source]

  console.print("\n[bold]AgentVault Memory Sync[/bold]\n")

  import time
  all_sessions = []

  for adapter in adapters:
    if not adapter.detect():
      continue

    last = timestamps.get(adapter.name)
    sessions = adapter.get_all_sessions(since_mtime=last)
    if sessions:
      console.print(f"  [bold]{adapter.name}[/bold]: {len(sessions)} new sessions")
      all_sessions.extend(sessions)
    else:
      console.print(f"  [dim]{adapter.name}: up to date[/dim]")

  if not all_sessions:
    console.print("\n  Everything is up to date.\n")
    return

  console.print("\n  Writing to ChromaDB...")
  result = ingest_sessions(all_sessions, store)
  console.print(
    f"    [green]\u2713[/green] {result['chunks_added']} chunks indexed"
  )

  obsidian_vault = config.get("obsidian_vault")
  if obsidian_vault:
    vault_path = Path(obsidian_vault)
    for session in all_sessions:
      try:
        write_session(session, vault_path)
      except Exception:
        pass

  # Update timestamps
  for adapter in adapters:
    if adapter.detect():
      timestamps[adapter.name] = time.time()
  config["last_ingest_timestamp"] = timestamps
  save_config(config)

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

    project = meta.get("project", "?")
    source_name = meta.get("source", "?")
    branch = meta.get("git_branch", "")
    date = meta.get("timestamp", "?")[:10]

    # Header line with relevance badge
    header = f"[bold]#{i}[/bold] [green]{relevance}[/green]"
    header += f" [cyan]{project}[/cyan]"
    header += f" [dim]({source_name})[/dim]"
    if branch:
      header += f" [dim]branch:{branch}[/dim]"
    header += f" [dim]{date}[/dim]"
    console.print(header)

    # Truncate long content for terminal display
    content = hit["content"]
    if len(content) > 400:
      content = content[:400] + "..."
    # Indent content for readability
    for line in content.split("\n")[:8]:
      console.print(f"  {line}")
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
  table.add_row("Total chunks", str(stats.get("total_chunks", 0)))
  table.add_row("Total sessions", str(stats.get("total_sessions", 0)))
  table.add_row(
    "Obsidian vault",
    config.get("obsidian_vault") or "not configured",
  )

  console.print()
  console.print(table)

  # Per-source breakdown
  sources_detail = stats.get("sources_detail", {})
  if sources_detail:
    src_table = Table(title="By Source")
    src_table.add_column("Tool", style="bold")
    src_table.add_column("Chunks", justify="right")
    for src, count in sources_detail.items():
      src_table.add_row(src, str(count))
    console.print(src_table)

  # Per-project breakdown
  projects_detail = stats.get("projects_detail", {})
  if projects_detail:
    proj_table = Table(title="By Project")
    proj_table.add_column("Project", style="bold")
    proj_table.add_column("Chunks", justify="right")
    for proj, count in projects_detail.items():
      proj_table.add_row(proj, str(count))
    console.print(proj_table)

  console.print()


@cli.command()
@click.argument("output", type=click.Path())
@click.option("--format", "fmt", type=click.Choice(["json", "markdown"]), default="json")
@click.option("--project", "-p", type=str, default=None, help="Filter by project")
def export(output: str, fmt: str, project: str | None):
  """Export vault data to JSON or Markdown."""
  from agentvault.core.store import VaultStore

  store = VaultStore()
  stats = store.get_stats()
  total = stats.get("total_chunks", 0)

  if total == 0:
    console.print("\n  Vault is empty. Nothing to export.\n")
    return

  # Get all chunks (with optional project filter)
  where = {"project": project} if project else None
  results = store.collection.get(
    limit=total,
    include=["documents", "metadatas"],
    where=where,
  )

  out_path = Path(output)

  if fmt == "json":
    import json as json_mod
    data = []
    for i in range(len(results["ids"])):
      data.append({
        "id": results["ids"][i],
        "content": results["documents"][i],
        "metadata": results["metadatas"][i],
      })
    out_path.write_text(
      json_mod.dumps(data, indent=2), encoding="utf-8"
    )

  elif fmt == "markdown":
    lines = ["# AgentVault Memory Export\n"]
    lines.append(f"Total chunks: {len(results['ids'])}\n")
    for i in range(len(results["ids"])):
      meta = results["metadatas"][i]
      date = meta.get("timestamp", "?")[:10]
      lines.append(f"## {meta.get('project', '?')} — {date}")
      lines.append(f"*Source: {meta.get('source', '?')}*\n")
      lines.append(results["documents"][i])
      lines.append("\n---\n")
    out_path.write_text("\n".join(lines), encoding="utf-8")

  console.print(
    f"\n  [green]\u2713[/green] Exported {len(results['ids'])} chunks "
    f"to {out_path}\n"
  )


@cli.command(name="session-start")
def session_start():
  """SessionStart hook — emit wake-up + project context for new sessions."""
  import sys

  try:
    event = json.loads(sys.stdin.read() or "{}")
  except Exception:
    event = {}

  cwd = event.get("cwd") or ""
  project = Path(cwd).name if cwd else None

  config = load_config()
  if config.get("auto_inject") is False:
    sys.exit(0)

  try:
    from agentvault.core.store import VaultStore
    store = VaultStore(persist_dir=config.get("chromadb_dir"))
    stats = store.get_stats()
  except Exception:
    sys.exit(0)

  if stats["total_chunks"] == 0:
    sys.exit(0)

  lines = []
  src = stats.get("sources_detail", {})
  top_projects = list(stats.get("projects_detail", {}).keys())[:5]
  lines.append(
    f"AgentVault Memory: {stats.get('total_sessions', 0)} sessions, "
    f"{stats['total_chunks']} chunks indexed."
  )
  if src:
    src_str = ", ".join(f"{s}({c})" for s, c in src.items())
    lines.append(f"Sources: {src_str}.")
  if top_projects:
    lines.append(f"Active projects: {', '.join(top_projects)}.")

  if project:
    try:
      results = store.search(
        query=f"recent work on {project}",
        top_k=3,
        project=project,
        min_relevance=0.30,
        time_decay=True,
      )
    except Exception:
      results = []

    if results:
      lines.append(f"\nRecent activity in **{project}**:")
      for r in results:
        meta = r.get("metadata") or {}
        ts = (meta.get("timestamp") or "")[:10]
        snippet = (r.get("content") or "").replace("\n", " ").strip()
        if len(snippet) > 180:
          snippet = snippet[:180] + "..."
        lines.append(f"- [{ts}] {snippet}")

  lines.append(
    "\n_Use `vault_search_lite` for past conversations, "
    "`vault_decisions` for past decisions._"
  )

  output = {
    "hookSpecificOutput": {
      "hookEventName": "SessionStart",
      "additionalContext": "\n".join(lines),
    }
  }
  print(json.dumps(output))


@cli.command(name="inject-context")
def inject_context():
  """UserPromptSubmit hook \u2014 inject relevant past context before user's prompt.

  Reads Claude Code hook event JSON from stdin, searches the vault for relevant
  past context, and emits a JSON envelope that Claude Code injects into the
  conversation. Designed to be fast and silent \u2014 fails open on any error.
  """
  import sys

  INTERJECTIONS = {
    "yes", "no", "ok", "okay", "continue", "go", "do it",
    "please", "yep", "nope", "sure", "cancel", "stop",
  }
  MAX_RESULTS = 3
  MIN_RELEVANCE = 0.35
  SNIPPET_LEN = 220

  try:
    event = json.loads(sys.stdin.read() or "{}")
  except Exception:
    sys.exit(0)

  prompt = (event.get("prompt") or "").strip()
  cwd = event.get("cwd") or ""
  current_session = event.get("session_id") or ""

  if len(prompt) < 8 or prompt.lower() in INTERJECTIONS:
    sys.exit(0)

  config = load_config()
  if config.get("auto_inject") is False:
    sys.exit(0)

  project = Path(cwd).name if cwd else None

  try:
    from agentvault.core.store import VaultStore
    store = VaultStore(persist_dir=config.get("chromadb_dir"))
    results = store.search(
      query=prompt,
      top_k=MAX_RESULTS + 2,  # buffer to allow filtering current session
      project=project,
      min_relevance=MIN_RELEVANCE,
    )
  except Exception:
    sys.exit(0)

  if current_session:
    results = [
      r for r in results
      if (r.get("metadata") or {}).get("session_id") != current_session
    ]
  results = results[:MAX_RESULTS]

  if not results:
    sys.exit(0)

  lines = ["## Relevant past context (from AgentVault Memory):"]
  for r in results:
    meta = r.get("metadata") or {}
    proj = meta.get("project", "?")
    src = meta.get("source", "?")
    ts = (meta.get("timestamp") or "")[:10]
    snippet = (r.get("content") or "").replace("\n", " ").strip()
    if len(snippet) > SNIPPET_LEN:
      snippet = snippet[:SNIPPET_LEN] + "\u2026"
    lines.append(f"- [{proj} \u00b7 {src} \u00b7 {ts}] {snippet}")
  lines.append(
    "_If a result looks relevant, call `vault_search` for full content._"
  )

  output = {
    "hookSpecificOutput": {
      "hookEventName": "UserPromptSubmit",
      "additionalContext": "\n".join(lines),
    }
  }
  print(json.dumps(output))


@cli.command(name="mcp-install")
def mcp_install():
  """Install AgentVault MCP server + auto-save + context-injection hooks."""
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
    console.print("    [green]\u2713[/green] Claude Code Stop hook installed")
  except Exception as e:
    console.print(f"    [yellow]![/yellow] {e}")

  console.print("\n  [bold]Installing context-injection hook:[/bold]")
  try:
    _install_inject_context_hook()
    console.print(
      "    [green]\u2713[/green] Claude Code UserPromptSubmit hook installed"
    )
  except Exception as e:
    console.print(f"    [yellow]![/yellow] {e}")

  console.print("\n  [bold]Installing session-start hook:[/bold]")
  try:
    _install_session_start_hook()
    console.print(
      "    [green]\u2713[/green] Claude Code SessionStart hook installed"
    )
  except Exception as e:
    console.print(f"    [yellow]![/yellow] {e}")

  console.print("\n  Restart your AI tools to activate.\n")


@cli.command()
@click.option("--session", "session_id", type=str, default=None, help="Delete by session ID")
@click.option("--project", "-p", type=str, default=None, help="Delete by project")
@click.option("--source", "-s", type=str, default=None, help="Delete by source tool")
@click.option("--all", "delete_all", is_flag=True, default=False, help="Delete everything")
def forget(session_id: str | None, project: str | None, source: str | None, delete_all: bool):
  """Delete sessions from the vault."""
  from agentvault.core.store import VaultStore

  if not any([session_id, project, source, delete_all]):
    console.print("\n  [yellow]![/yellow] Specify what to forget: "
                  "--session, --project, --source, or --all\n")
    return

  store = VaultStore()

  if delete_all:
    if not click.confirm("  This will delete ALL data from the vault. Are you sure?"):
      console.print("  Cancelled.\n")
      return
    count = store.delete_all()
    console.print(f"\n  [green]\u2713[/green] Deleted {count} chunks (all data).\n")

  elif session_id:
    count = store.delete_by_session(session_id)
    short = session_id[:8]
    console.print(f"\n  [green]\u2713[/green] Deleted {count} chunks for session {short}.\n")

  elif project:
    if not click.confirm(f"  Delete all data for project '{project}'?"):
      console.print("  Cancelled.\n")
      return
    count = store.delete_by_project(project)
    console.print(f"\n  [green]\u2713[/green] Deleted {count} chunks for project '{project}'.\n")

  elif source:
    if not click.confirm(f"  Delete all data from '{source}'?"):
      console.print("  Cancelled.\n")
      return
    count = store.delete_by_source(source)
    console.print(f"\n  [green]\u2713[/green] Deleted {count} chunks from '{source}'.\n")


@cli.command()
@click.option("--project", "-p", type=str, default=None, help="Filter by project")
@click.option("--export", "export_path", type=click.Path(), default=None, help="Export to markdown")
def decisions(project: str | None, export_path: str | None):
  """Extract and display decisions from your conversation history."""
  from agentvault.core.decisions import Decision, extract_decisions, format_decisions_markdown
  from agentvault.core.store import VaultStore

  store = VaultStore()

  # Search for chunks that likely contain decisions
  decision_keywords = [
    "decided", "chose", "going with", "will use",
    "agreed", "switching to", "plan is", "recommend",
  ]
  query = " ".join(decision_keywords)
  results = store.search(query=query, top_k=50, project=project)

  if not results:
    console.print("\n  No conversations found to analyze.\n")
    return

  # Extract decisions from search results
  all_decisions: list[Decision] = []
  seen: set[str] = set()

  for hit in results:
    meta = hit["metadata"]
    content = hit["content"]

    # Create a minimal session-like object for the extractor
    from agentvault.core.schema import AgentSession, Exchange
    mini_session = AgentSession(
      id=meta.get("session_id", ""),
      source=meta.get("source", ""),
      project=meta.get("project", ""),
      started_at=meta.get("timestamp", ""),
      ended_at="",
      working_directory="",
      exchanges=[Exchange(role="assistant", content=content, timestamp=meta.get("timestamp", ""))],
    )
    extracted = extract_decisions(mini_session)
    for d in extracted:
      key = d.text.lower()[:80]
      if key not in seen:
        seen.add(key)
        all_decisions.append(d)

  if not all_decisions:
    console.print("\n  No decisions found in your conversations.\n")
    return

  console.print(f"\n[bold]Found {len(all_decisions)} decisions:[/bold]\n")
  for d in all_decisions:
    date = d.timestamp[:10] if d.timestamp else "?"
    console.print(
      f"  [cyan]{d.project}[/cyan] ({d.source}, {date})"
    )
    console.print(f"    {d.text}\n")

  if export_path:
    md = format_decisions_markdown(all_decisions)
    Path(export_path).write_text(md, encoding="utf-8")
    console.print(f"  [green]\u2713[/green] Exported to {export_path}\n")


if __name__ == "__main__":
  cli()
