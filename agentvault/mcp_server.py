"""MCP server for AgentVault Memory — exposes search tools to AI agents.

Run with:
  python -m agentvault.mcp_server

Or configure in Claude Code:
  claude mcp add agentvault -- python -m agentvault.mcp_server
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any

from agentvault.config import load_config
from agentvault.core.optimizer import compact_metadata, dedup_results, optimize_content
from agentvault.core.store import VaultStore

# MCP protocol constants
JSONRPC_VERSION = "2.0"

# Security limits
MAX_TOP_K = 50
MAX_QUERY_LENGTH = 10_000
MAX_LINE_LENGTH = 1_000_000  # 1MB per line
DEFAULT_MIN_RELEVANCE = 0.25  # Drop results below 25% relevance


def _make_response(id: Any, result: Any) -> dict:
  return {"jsonrpc": JSONRPC_VERSION, "id": id, "result": result}


def _make_error(id: Any, code: int, message: str) -> dict:
  return {"jsonrpc": JSONRPC_VERSION, "id": id, "error": {"code": code, "message": message}}


def _validate_string(value: Any, name: str, max_length: int = MAX_QUERY_LENGTH) -> str:
  """Validate and sanitize a string input."""
  if not isinstance(value, str):
    raise ValueError(f"{name} must be a string")
  if len(value) > max_length:
    raise ValueError(f"{name} exceeds maximum length of {max_length}")
  return value


def _validate_top_k(value: Any) -> int:
  """Validate top_k is a reasonable positive integer."""
  if value is None:
    return 5
  try:
    k = int(value)
  except (TypeError, ValueError):
    return 5
  return max(1, min(k, MAX_TOP_K))


def _get_tools() -> list[dict]:
  return [
    {
      "name": "vault_search",
      "description": "Semantic search across all AI agent conversation history. Use this to find past decisions, debugging sessions, code discussions, and anything discussed in previous sessions.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "What to search for — natural language query",
            "maxLength": MAX_QUERY_LENGTH,
          },
          "project": {
            "type": "string",
            "description": "Filter by project name (e.g. 'my-app', 'backend-api')",
          },
          "source": {
            "type": "string",
            "description": "Filter by tool ('claude-code', 'opencode', 'codex', 'cursor')",
          },
          "top_k": {
            "type": "integer",
            "description": f"Number of results to return (default: 5, max: {MAX_TOP_K})",
            "default": 5,
            "maximum": MAX_TOP_K,
          },
        },
        "required": ["query"],
      },
    },
    {
      "name": "vault_project_context",
      "description": "Get recent conversation context for a specific project. Use when starting work on a project to understand what was discussed recently.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "project": {
            "type": "string",
            "description": "Project name to get context for",
          },
          "topic": {
            "type": "string",
            "description": "Optional topic to focus on",
          },
        },
        "required": ["project"],
      },
    },
    {
      "name": "vault_cross_reference",
      "description": "Search across all projects to find if a similar problem was solved before. Great for finding reusable solutions.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "The problem or pattern to search for across all projects",
            "maxLength": MAX_QUERY_LENGTH,
          },
        },
        "required": ["query"],
      },
    },
    {
      "name": "vault_status",
      "description": "Get an overview of the vault — total sessions, projects, sources, and chunk count.",
      "inputSchema": {
        "type": "object",
        "properties": {},
      },
    },
    {
      "name": "vault_search_lite",
      "description": "Token-efficient search — returns short summaries instead of full content. Use this first, then vault_search for details on specific results. Saves ~80% tokens.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "What to search for",
            "maxLength": MAX_QUERY_LENGTH,
          },
          "project": {
            "type": "string",
            "description": "Filter by project name",
          },
          "top_k": {
            "type": "integer",
            "description": f"Number of results (default: 10, max: {MAX_TOP_K})",
            "default": 10,
          },
        },
        "required": ["query"],
      },
    },
    {
      "name": "vault_decisions",
      "description": "Find decisions made in past conversations. Returns extracted decisions like 'chose X over Y because...' from your AI session history.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "project": {
            "type": "string",
            "description": "Filter decisions by project name",
          },
        },
      },
    },
    {
      "name": "vault_wake_up",
      "description": "Call this ONCE at session start. Returns a tiny context summary (~50 tokens) of recent projects and activity. Costs almost nothing and gives you baseline awareness of what the user has been working on.",
      "inputSchema": {
        "type": "object",
        "properties": {},
      },
    },
  ]


class MCPServer:
  """Minimal MCP server using stdio transport."""

  def __init__(self):
    config = load_config()
    self.store = VaultStore(
      persist_dir=config.get("chromadb_dir"),
      collection_name=config.get("collection_name", "agentvault_chunks"),
    )

  def handle_request(self, request: dict) -> dict:
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    # Validate method is a string
    if not isinstance(method, str):
      return _make_error(req_id, -32600, "Invalid request: method must be a string")

    if method == "initialize":
      return _make_response(req_id, {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "agentvault", "version": "0.1.0"},
      })

    elif method == "tools/list":
      return _make_response(req_id, {"tools": _get_tools()})

    elif method == "tools/call":
      return self._handle_tool_call(req_id, params)

    elif method == "notifications/initialized":
      return None  # No response for notifications

    elif method == "ping":
      return _make_response(req_id, {})

    else:
      return _make_error(req_id, -32601, f"Method not found: {method}")

  def _handle_tool_call(self, req_id: Any, params: dict) -> dict:
    tool_name = params.get("name", "")
    args = params.get("arguments", {})

    try:
      if tool_name == "vault_search":
        query = _validate_string(args.get("query", ""), "query")
        top_k = _validate_top_k(args.get("top_k"))
        project = args.get("project")
        source = args.get("source")
        if project:
          _validate_string(project, "project", max_length=200)
        if source:
          _validate_string(source, "source", max_length=100)

        results = self.store.search(
          query=query,
          top_k=top_k,
          project=project,
          source=source,
          min_relevance=DEFAULT_MIN_RELEVANCE,
        )
        text = self._format_search_results(results)

      elif tool_name == "vault_project_context":
        project = _validate_string(args.get("project", ""), "project", max_length=200)
        topic = args.get("topic")
        if topic:
          _validate_string(topic, "topic")
        query = topic or f"recent work on {project}"
        results = self.store.search(
          query=query, top_k=8, project=project,
          min_relevance=DEFAULT_MIN_RELEVANCE,
          time_decay=True,
        )
        text = self._format_search_results(results)

      elif tool_name == "vault_cross_reference":
        query = _validate_string(args.get("query", ""), "query")
        results = self.store.search(
          query=query, top_k=10,
          min_relevance=DEFAULT_MIN_RELEVANCE,
        )
        text = self._format_search_results(results)

      elif tool_name == "vault_search_lite":
        query = _validate_string(args.get("query", ""), "query")
        top_k = _validate_top_k(args.get("top_k", 10))
        project = args.get("project")
        if project:
          _validate_string(project, "project", max_length=200)

        results = self.store.search(
          query=query, top_k=top_k, project=project,
          min_relevance=DEFAULT_MIN_RELEVANCE,
          time_decay=True,
        )
        results = dedup_results(results)

        if not results:
          text = "No results found."
        else:
          lines = [f"Found {len(results)} results (summaries only):\n"]
          for i, hit in enumerate(results, 1):
            meta = hit["metadata"]
            distance = hit.get("distance")
            rel = f"{1 - distance:.0%}" if distance is not None else "?"
            meta_line = compact_metadata(meta)

            # Extract first meaningful line as preview
            content = optimize_content(hit["content"])
            first_line = ""
            for line in content.split("\n"):
              line = line.strip()
              if line and not line.startswith("[") and len(line) > 10:
                first_line = line[:120]
                if len(line) > 120:
                  first_line += "..."
                break

            lines.append(f"[{i}] {rel} — {meta_line}")
            if first_line:
              lines.append(f"    {first_line}")

          lines.append(
            "\nUse vault_search with the same query "
            "for full content of specific results."
          )
          text = "\n".join(lines)

      elif tool_name == "vault_wake_up":
        stats = self.store.get_stats()
        if stats["total_chunks"] == 0:
          text = "Vault is empty. No prior session history available."
        else:
          # Compact summary: projects with chunk counts, sorted by activity
          proj = stats.get("projects_detail", {})
          top_projects = list(proj.keys())[:5]
          src = stats.get("sources_detail", {})
          sessions = stats.get("total_sessions", 0)

          lines = [
            f"Memory: {sessions} sessions, "
            f"{stats['total_chunks']} chunks.",
            f"Sources: {', '.join(f'{s}({c})' for s, c in src.items())}.",
            f"Active projects: {', '.join(top_projects)}.",
            "Use vault_search_lite to find specific conversations.",
          ]
          text = " ".join(lines)

      elif tool_name == "vault_status":
        stats = self.store.get_stats()
        text = (
          f"AgentVault Memory Status:\n"
          f"  Total chunks: {stats['total_chunks']}\n"
          f"  Projects: {', '.join(stats['projects']) or 'none'}\n"
          f"  Sources: {', '.join(stats['sources']) or 'none'}"
        )

      elif tool_name == "vault_decisions":
        from agentvault.core.decisions import Decision, extract_decisions
        from agentvault.core.schema import AgentSession, Exchange

        project = args.get("project")
        if project:
          _validate_string(project, "project", max_length=200)

        query = "decided chose going with will use agreed switching plan recommend"
        results = self.store.search(query=query, top_k=30, project=project)

        all_decisions: list[Decision] = []
        seen: set[str] = set()
        for hit in results:
          meta = hit["metadata"]
          mini = AgentSession(
            id=meta.get("session_id", ""),
            source=meta.get("source", ""),
            project=meta.get("project", ""),
            started_at=meta.get("timestamp", ""),
            ended_at="",
            working_directory="",
            exchanges=[Exchange(
              role="assistant",
              content=hit["content"],
              timestamp=meta.get("timestamp", ""),
            )],
          )
          for d in extract_decisions(mini):
            key = d.text.lower()[:80]
            if key not in seen:
              seen.add(key)
              all_decisions.append(d)

        if not all_decisions:
          text = "No decisions found in the vault."
        else:
          lines = [f"Found {len(all_decisions)} decisions:\n"]
          for d in all_decisions:
            date = d.timestamp[:10] if d.timestamp else "?"
            lines.append(f"- [{d.project}, {d.source}, {date}] {d.text}")
          text = "\n".join(lines)

      else:
        return _make_error(req_id, -32602, f"Unknown tool: {tool_name}")

      return _make_response(req_id, {
        "content": [{"type": "text", "text": text}],
      })

    except ValueError as e:
      # Validation errors are safe to return
      return _make_response(req_id, {
        "content": [{"type": "text", "text": f"Validation error: {e}"}],
        "isError": True,
      })
    except Exception:
      # Log full error to stderr, return generic message to client
      print(f"MCP tool error: {traceback.format_exc()}", file=sys.stderr)
      return _make_response(req_id, {
        "content": [{"type": "text", "text": "An internal error occurred while processing the request."}],
        "isError": True,
      })

  def _format_search_results(self, results: list[dict]) -> str:
    if not results:
      return "No matching results found in the vault."

    # Deduplicate near-identical results
    results = dedup_results(results)

    parts = [f"Found {len(results)} results:\n"]
    for i, hit in enumerate(results, 1):
      meta = hit["metadata"]
      distance = hit.get("distance")
      relevance = f"{1 - distance:.0%}" if distance is not None else "?"

      # Compact metadata line
      meta_line = compact_metadata(meta)

      # Optimize content — strip tool noise, truncate code blocks
      content = optimize_content(hit["content"])

      # Cap content length to save tokens
      if len(content) > 600:
        content = content[:600] + "..."

      parts.append(
        f"[{i}] {relevance} — {meta_line}\n{content}\n"
      )
    return "\n".join(parts)

  def run(self):
    """Run the MCP server on stdio."""
    for line in sys.stdin:
      # Enforce max line length to prevent OOM
      if len(line) > MAX_LINE_LENGTH:
        continue

      line = line.strip()
      if not line:
        continue

      try:
        request = json.loads(line)
      except (json.JSONDecodeError, MemoryError):
        continue

      response = self.handle_request(request)
      if response is not None:
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


def main():
  server = MCPServer()
  server.run()


if __name__ == "__main__":
  main()
