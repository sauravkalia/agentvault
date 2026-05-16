"""Smoke tests for the web viewer routes."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from agentvault.web import create_app  # noqa: E402


class FakeCollection:
  def __init__(self, ids=None, docs=None, metas=None):
    self.ids = ids or []
    self.docs = docs or []
    self.metas = metas or []

  def count(self):
    return len(self.ids)

  def get(self, *, limit=None, include=None, where=None, offset=None):
    out_ids, out_docs, out_metas = [], [], []
    for i, cid in enumerate(self.ids):
      meta = self.metas[i]
      if where and not all(meta.get(k) == v for k, v in where.items()):
        continue
      out_ids.append(cid)
      out_docs.append(self.docs[i])
      out_metas.append(meta)
    return {"ids": out_ids, "documents": out_docs, "metadatas": out_metas}


class FakeStore:
  def __init__(self, chunks=None, hits=None):
    chunks = chunks or []
    ids = [c["id"] for c in chunks]
    docs = [c["content"] for c in chunks]
    metas = [c["meta"] for c in chunks]
    self.collection = FakeCollection(ids, docs, metas)
    self._hits = hits or []

  def get_stats(self):
    projects: dict[str, int] = {}
    sources: dict[str, int] = {}
    sessions = set()
    for m in self.collection.metas:
      projects[m["project"]] = projects.get(m["project"], 0) + 1
      sources[m["source"]] = sources.get(m["source"], 0) + 1
      sessions.add(m["session_id"])
    return {
      "total_chunks": self.collection.count(),
      "total_sessions": len(sessions),
      "projects": sorted(projects.keys()),
      "projects_detail": dict(sorted(projects.items(), key=lambda x: -x[1])),
      "sources": sorted(sources.keys()),
      "sources_detail": dict(sorted(sources.items(), key=lambda x: -x[1])),
    }

  def search(self, *, query, top_k=5, project=None, source=None,
             mode="hybrid", min_relevance=0.0, time_decay=False, **kw):
    # Return seeded hits; if a project filter is set, narrow.
    out = []
    for h in self._hits:
      if project and (h.get("metadata") or {}).get("project") != project:
        continue
      out.append(dict(h))
    return out[:top_k]


def _chunk(cid="c1", session="s1", project="proj-a", source="claude-code",
          content="some content here", ts="2026-04-01T10:00:00Z", idx=0):
  return {
    "id": cid,
    "content": content,
    "meta": {
      "session_id": session,
      "project": project,
      "source": source,
      "timestamp": ts,
      "chunk_index": idx,
      "git_branch": "main",
    },
  }


def _hit(content, project="proj-a", source="claude-code", session="s1",
         ts="2026-04-01T10:00:00Z", score=0.8):
  return {
    "id": f"hit-{session}",
    "content": content,
    "metadata": {
      "project": project, "source": source,
      "session_id": session, "timestamp": ts,
    },
    "distance": 0.2,
    "score": score,
  }


def _client(store):
  app = create_app(store)
  return TestClient(app)


# ---------- routes ----------

def test_home_empty_vault():
  client = _client(FakeStore())
  r = client.get("/")
  assert r.status_code == 200
  assert "Vault is empty" in r.text


def test_home_with_data():
  store = FakeStore(chunks=[
    _chunk("c1", "s1", "proj-a"),
    _chunk("c2", "s2", "proj-b"),
  ])
  client = _client(store)
  r = client.get("/")
  assert r.status_code == 200
  assert "proj-a" in r.text
  assert "proj-b" in r.text
  assert "claude-code" in r.text


def test_search_empty_query_shows_form():
  client = _client(FakeStore(chunks=[_chunk()]))
  r = client.get("/search")
  assert r.status_code == 200
  assert "Type a query above" in r.text


def test_search_with_query_runs_search():
  store = FakeStore(
    chunks=[_chunk()],
    hits=[_hit("matched chunk for the query")],
  )
  client = _client(store)
  r = client.get("/search", params={"q": "anything"})
  assert r.status_code == 200
  assert "matched chunk" in r.text
  assert "1 results" in r.text


def test_search_no_matches():
  store = FakeStore(chunks=[_chunk()], hits=[])
  client = _client(store)
  r = client.get("/search", params={"q": "nothing"})
  assert r.status_code == 200
  assert "No matches" in r.text


def test_search_html_escapes_query():
  store = FakeStore(chunks=[_chunk()], hits=[])
  client = _client(store)
  r = client.get("/search", params={"q": "<script>alert(1)</script>"})
  assert "<script>alert(1)</script>" not in r.text
  assert "&lt;script&gt;" in r.text


def test_projects_list():
  store = FakeStore(chunks=[_chunk("c1", project="proj-a")])
  client = _client(store)
  r = client.get("/projects")
  assert r.status_code == 200
  assert "proj-a" in r.text


def test_projects_empty():
  client = _client(FakeStore())
  r = client.get("/projects")
  assert r.status_code == 200
  assert "No projects" in r.text


def test_project_detail_empty():
  store = FakeStore(chunks=[_chunk(project="proj-a")], hits=[])
  client = _client(store)
  r = client.get("/projects/proj-a")
  assert r.status_code == 200
  assert "No activity" in r.text


def test_project_detail_with_activity():
  hits = [_hit("recent discussion about auth", project="proj-a")]
  store = FakeStore(chunks=[_chunk(project="proj-a")], hits=hits)
  client = _client(store)
  r = client.get("/projects/proj-a")
  assert r.status_code == 200
  assert "recent discussion about auth" in r.text


def test_session_detail_lists_chunks():
  store = FakeStore(chunks=[
    _chunk("c1", session="s1", content="first chunk", idx=0),
    _chunk("c2", session="s1", content="second chunk", idx=1),
    _chunk("c3", session="s2", content="other session", idx=0),
  ])
  client = _client(store)
  r = client.get("/sessions/s1")
  assert r.status_code == 200
  assert "first chunk" in r.text
  assert "second chunk" in r.text
  assert "other session" not in r.text


def test_session_detail_not_found():
  client = _client(FakeStore())
  r = client.get("/sessions/nonexistent")
  assert r.status_code == 200
  assert "No chunks found" in r.text


def test_api_stats_json():
  store = FakeStore(chunks=[_chunk()])
  client = _client(store)
  r = client.get("/api/stats")
  assert r.status_code == 200
  data = r.json()
  assert data["total_chunks"] == 1
  assert "proj-a" in data["projects_detail"]
