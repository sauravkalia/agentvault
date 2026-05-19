"""Localhost web viewer for the AgentVault Memory store.

Optional feature — depends on FastAPI + uvicorn, installed via the `[ui]`
extras. The CLI's `agentvault serve` entry point lazily imports this
module so the core install stays slim.

Routes:
  GET /                      home (stats overview + nav)
  GET /search                hybrid search form + results
  GET /projects              list of indexed projects
  GET /projects/{name}       project detail (sessions, decisions, patterns)
  GET /sessions/{id}         all chunks for one session
  GET /api/stats             JSON stats (for ad-hoc scripts)

HTML is rendered inline with f-strings + `html.escape`. Jinja is
deliberately not pulled in — the templates are short and shared via the
`_layout` helper.
"""

from __future__ import annotations

import html
from typing import Any, Optional
from urllib.parse import quote_plus

# These imports are inside the module so callers that only want the CLI
# don't pay the FastAPI import cost. If the module is imported at all,
# the extras are assumed present.
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

_CSS = """
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  margin: 0; padding: 0; color: #222; background: #fafafa;
}
header {
  background: #1a1a1a; color: #fff; padding: 1rem 2rem;
  display: flex; align-items: center; gap: 2rem;
}
header h1 { margin: 0; font-size: 1.1rem; font-weight: 600; }
header nav a { color: #aaa; text-decoration: none; margin-right: 1rem; }
header nav a:hover { color: #fff; }
main { max-width: 1100px; margin: 0 auto; padding: 2rem; }
h2 { margin-top: 0; }
form.search { display: flex; gap: 0.5rem; margin-bottom: 2rem; }
form.search input[type=text] {
  flex: 1; padding: 0.5rem 0.75rem; font-size: 1rem;
  border: 1px solid #ccc; border-radius: 4px;
}
form.search button {
  padding: 0.5rem 1rem; background: #1a1a1a; color: #fff; border: 0;
  border-radius: 4px; cursor: pointer;
}
.card {
  background: #fff; border: 1px solid #e5e5e5; border-radius: 6px;
  padding: 1rem 1.25rem; margin-bottom: 1rem;
}
.meta { color: #666; font-size: 0.85rem; margin-top: 0.25rem; }
.tag {
  display: inline-block; padding: 0.1rem 0.5rem; border-radius: 999px;
  background: #eef; color: #224; font-size: 0.75rem; margin-right: 0.25rem;
}
pre {
  white-space: pre-wrap; word-break: break-word; background: #f4f4f4;
  padding: 0.75rem; border-radius: 4px; font-size: 0.85rem;
  max-height: 400px; overflow-y: auto;
}
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #eee; }
th { font-size: 0.85rem; color: #555; }
.empty { color: #888; font-style: italic; }
a.session-link { color: #1a4dba; text-decoration: none; }
a.session-link:hover { text-decoration: underline; }
"""


def _layout(title: str, body: str) -> str:
  return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)} — AgentVault Memory</title>
  <style>{_CSS}</style>
</head>
<body>
  <header>
    <h1>AgentVault Memory</h1>
    <nav>
      <a href="/">Home</a>
      <a href="/search">Search</a>
      <a href="/projects">Projects</a>
    </nav>
  </header>
  <main>{body}</main>
</body>
</html>"""


def _chunk_card(hit: dict) -> str:
  meta = hit.get("metadata") or {}
  proj = html.escape(meta.get("project") or "?")
  src = html.escape(meta.get("source") or "?")
  date = html.escape((meta.get("timestamp") or "")[:10])
  sid = html.escape(meta.get("session_id") or "")
  if sid:
    sid_link = (
      f'<a class="session-link" href="/sessions/{quote_plus(sid)}">'
      f'{sid[:12] or "?"}</a>'
    )
  else:
    sid_link = "?"
  rel = ""
  if hit.get("score") is not None:
    rel = f'<span class="tag">{hit["score"] * 100:.0f}% score</span>'
  elif hit.get("distance") is not None:
    rel = f'<span class="tag">{(1 - hit["distance"]) * 100:.0f}% match</span>'
  content = html.escape(hit.get("content") or "")
  if len(content) > 1200:
    content = content[:1200] + "…"
  return f"""<div class="card">
    {rel}<span class="tag">{proj}</span><span class="tag">{src}</span>
    <div class="meta">{date} · session {sid_link}</div>
    <pre>{content}</pre>
  </div>"""


def _stats_summary(store: Any) -> dict:
  try:
    return store.get_stats()
  except Exception:
    return {"total_chunks": 0, "total_sessions": 0,
            "projects_detail": {}, "sources_detail": {}}


def _home(store: Any) -> str:
  stats = _stats_summary(store)
  total = stats.get("total_chunks", 0)
  sessions = stats.get("total_sessions", 0)
  projects = stats.get("projects_detail", {})
  sources = stats.get("sources_detail", {})

  if total == 0:
    body = (
      "<h2>Vault is empty</h2>"
      "<p>Run <code>agentvault ingest</code> to import your AI session history.</p>"
    )
    return _layout("Home", body)

  proj_rows = "".join(
    f"<tr><td><a class='session-link' href='/projects/{quote_plus(p)}'>{html.escape(p)}</a></td>"
    f"<td>{n}</td></tr>"
    for p, n in list(projects.items())[:25]
  ) or "<tr><td colspan='2' class='empty'>none</td></tr>"
  src_rows = "".join(
    f"<tr><td>{html.escape(s)}</td><td>{n}</td></tr>"
    for s, n in sources.items()
  ) or "<tr><td colspan='2' class='empty'>none</td></tr>"

  body = f"""
    <h2>Overview</h2>
    <div class="card">
      <p><strong>{total}</strong> chunks · <strong>{sessions}</strong> sessions indexed.</p>
      <form class="search" action="/search" method="get">
        <input type="text" name="q" placeholder="Search past sessions…" autofocus>
        <button type="submit">Search</button>
      </form>
    </div>
    <div class="card">
      <h2>Projects</h2>
      <table><thead><tr><th>Project</th><th>Chunks</th></tr></thead>
      <tbody>{proj_rows}</tbody></table>
    </div>
    <div class="card">
      <h2>Sources</h2>
      <table><thead><tr><th>Source</th><th>Chunks</th></tr></thead>
      <tbody>{src_rows}</tbody></table>
    </div>
  """
  return _layout("Home", body)


def _search(store: Any, q: str, project: Optional[str]) -> str:
  q_safe = html.escape(q)
  proj_safe = html.escape(project or "")
  body_parts = [
    "<h2>Search</h2>",
    f"""<form class="search" action="/search" method="get">
      <input type="text" name="q" value="{q_safe}"
        placeholder="Search…" autofocus>
      <input type="text" name="project" value="{proj_safe}"
        placeholder="Project (optional)" style="max-width:200px">
      <button type="submit">Search</button>
    </form>""",
  ]

  if not q.strip():
    body_parts.append('<p class="empty">Type a query above.</p>')
    return _layout("Search", "".join(body_parts))

  try:
    hits = store.search(
      query=q, top_k=20, project=project or None,
      mode="hybrid", min_relevance=0.0,
    )
  except Exception as e:
    body_parts.append(f'<p class="empty">Search failed: {html.escape(str(e))}</p>')
    return _layout("Search", "".join(body_parts))

  if not hits:
    body_parts.append('<p class="empty">No matches.</p>')
  else:
    body_parts.append(f"<p>{len(hits)} results</p>")
    for h in hits:
      body_parts.append(_chunk_card(h))

  return _layout("Search", "".join(body_parts))


def _projects(store: Any) -> str:
  stats = _stats_summary(store)
  projects = stats.get("projects_detail", {})
  if not projects:
    body = "<h2>Projects</h2><p class='empty'>No projects indexed yet.</p>"
    return _layout("Projects", body)
  rows = "".join(
    f"<tr><td><a class='session-link' href='/projects/{quote_plus(p)}'>{html.escape(p)}</a></td>"
    f"<td>{n}</td></tr>"
    for p, n in projects.items()
  )
  body = f"""
    <h2>Projects</h2>
    <table><thead><tr><th>Project</th><th>Chunks</th></tr></thead>
    <tbody>{rows}</tbody></table>
  """
  return _layout("Projects", body)


def _project_detail(store: Any, name: str) -> str:
  # Recent activity: pull this project's chunks directly from Chroma and
  # sort by timestamp desc. No synthetic search query — avoids the case
  # where the embedding/FTS pipeline returns 0 hits even though the data
  # is in the store.
  try:
    raw = store.collection.get(
      where={"project": name},
      limit=200,
      include=["documents", "metadatas"],
    )
  except Exception:
    raw = {"ids": [], "documents": [], "metadatas": []}

  ids = raw.get("ids", []) or []
  if not ids:
    body = (
      f"<h2>{html.escape(name)}</h2>"
      "<p class='empty'>No activity indexed for this project.</p>"
    )
    return _layout(name, body)

  docs = raw.get("documents", []) or []
  metas = raw.get("metadatas", []) or []
  hits = []
  for i, cid in enumerate(ids):
    meta = metas[i] if i < len(metas) else {}
    hits.append({
      "id": cid,
      "content": docs[i] if i < len(docs) else "",
      "metadata": meta,
      "distance": None,
    })
  hits.sort(
    key=lambda h: (h.get("metadata") or {}).get("timestamp", ""),
    reverse=True,
  )
  hits = hits[:10]

  # Patterns & decisions, both heuristic — fail open.
  try:
    from agentvault.core.patterns import find_patterns
    patterns = find_patterns(store, project=name, min_sessions=2, top_n=8)
  except Exception:
    patterns = []

  try:
    from agentvault.core.todos import find_todos
    open_todos = find_todos(store, project=name, only_unresolved=True, top_n=10)
  except Exception:
    open_todos = []

  body_parts = [f"<h2>{html.escape(name)}</h2>"]

  if open_todos:
    todo_rows = "".join(
      f"<li>{html.escape(t.text)} <span class='meta'>({html.escape(t.date)})</span></li>"
      for t in open_todos
    )
    body_parts.append(
      f"<div class='card'><h2>Open TODOs ({len(open_todos)})</h2><ul>{todo_rows}</ul></div>"
    )

  if patterns:
    p_rows = "".join(
      f"<li><strong>{p.session_count} sessions</strong> — "
      f"{html.escape(p.example)}</li>"
      for p in patterns
    )
    body_parts.append(
      f"<div class='card'><h2>Recurring problems</h2><ul>{p_rows}</ul></div>"
    )

  body_parts.append("<h2>Recent activity</h2>")
  for h in hits:
    body_parts.append(_chunk_card(h))

  return _layout(name, "".join(body_parts))


def _session_detail(store: Any, sid: str) -> str:
  try:
    page = store.collection.get(
      where={"session_id": sid}, include=["documents", "metadatas"],
    )
  except Exception:
    page = {"ids": [], "documents": [], "metadatas": []}

  ids = page.get("ids", []) or []
  if not ids:
    body = (
      f"<h2>Session {html.escape(sid)}</h2>"
      "<p class='empty'>No chunks found for this session.</p>"
    )
    return _layout("Session", body)

  docs = page.get("documents", []) or []
  metas = page.get("metadatas", []) or []

  # Order by chunk_index when present.
  hits = []
  for i, cid in enumerate(ids):
    meta = metas[i] if i < len(metas) else {}
    hits.append({
      "id": cid,
      "content": docs[i] if i < len(docs) else "",
      "metadata": meta,
      "distance": None,
    })
  hits.sort(key=lambda h: (h.get("metadata") or {}).get("chunk_index", 0))

  first = hits[0]["metadata"] or {}
  proj = html.escape(first.get("project") or "?")
  src = html.escape(first.get("source") or "?")
  date = html.escape((first.get("timestamp") or "")[:10])

  body_parts = [
    f"<h2>Session <code>{html.escape(sid)}</code></h2>",
    f"<p class='meta'><span class='tag'>{proj}</span>"
    f"<span class='tag'>{src}</span> {date} · {len(hits)} chunks</p>",
  ]
  for h in hits:
    body_parts.append(_chunk_card(h))

  return _layout("Session", "".join(body_parts))


def create_app(store: Any) -> FastAPI:
  """Build a FastAPI app bound to a specific VaultStore instance."""
  app = FastAPI(title="AgentVault Memory")

  @app.get("/", response_class=HTMLResponse)
  def home(_: Request):
    return HTMLResponse(_home(store))

  @app.get("/search", response_class=HTMLResponse)
  def search(
    _: Request,
    q: str = Query(default=""),
    project: Optional[str] = Query(default=None),
  ):
    return HTMLResponse(_search(store, q, project))

  @app.get("/projects", response_class=HTMLResponse)
  def projects(_: Request):
    return HTMLResponse(_projects(store))

  @app.get("/projects/{name}", response_class=HTMLResponse)
  def project_detail(_: Request, name: str):
    return HTMLResponse(_project_detail(store, name))

  @app.get("/sessions/{sid}", response_class=HTMLResponse)
  def session_detail(_: Request, sid: str):
    return HTMLResponse(_session_detail(store, sid))

  @app.get("/api/stats")
  def api_stats(_: Request):
    return JSONResponse(_stats_summary(store))

  return app


def run(host: str = "127.0.0.1", port: int = 3777) -> None:
  """Programmatic launcher used by the `agentvault serve` CLI command."""
  import uvicorn

  from agentvault.config import load_config
  from agentvault.core.store import VaultStore

  config = load_config()
  store = VaultStore(persist_dir=config.get("chromadb_dir"))
  app = create_app(store)
  uvicorn.run(app, host=host, port=port, log_level="info")


__all__ = ["create_app", "run"]
