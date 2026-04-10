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
from agentvault.core.store import VaultStore

# MCP protocol constants
JSONRPC_VERSION = "2.0"

# Security limits
MAX_TOP_K = 50
MAX_QUERY_LENGTH = 10_000
MAX_LINE_LENGTH = 1_000_000  # 1MB per line


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
        )
        text = self._format_search_results(results)

      elif tool_name == "vault_project_context":
        project = _validate_string(args.get("project", ""), "project", max_length=200)
        topic = args.get("topic")
        if topic:
          _validate_string(topic, "topic")
        query = topic or f"recent work on {project}"
        results = self.store.search(query=query, top_k=8, project=project)
        text = self._format_search_results(results)

      elif tool_name == "vault_cross_reference":
        query = _validate_string(args.get("query", ""), "query")
        results = self.store.search(query=query, top_k=10)
        text = self._format_search_results(results)

      elif tool_name == "vault_status":
        stats = self.store.get_stats()
        text = (
          f"AgentVault Memory Status:\n"
          f"  Total chunks: {stats['total_chunks']}\n"
          f"  Projects: {', '.join(stats['projects']) or 'none'}\n"
          f"  Sources: {', '.join(stats['sources']) or 'none'}"
        )

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

    parts = [f"Found {len(results)} results:\n"]
    for i, hit in enumerate(results, 1):
      meta = hit["metadata"]
      distance = hit.get("distance")
      relevance = f" (relevance: {1 - distance:.1%})" if distance is not None else ""

      parts.append(
        f"--- Result {i}{relevance} ---\n"
        f"Project: {meta.get('project', '?')} | "
        f"Source: {meta.get('source', '?')} | "
        f"Branch: {meta.get('git_branch', '?')} | "
        f"Date: {meta.get('timestamp', '?')[:10]}\n\n"
        f"{hit['content']}\n"
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
