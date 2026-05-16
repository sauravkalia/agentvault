"""Tests for the stale-TODO extractor."""

from agentvault.core.todos import (
  _ChunkRecord,
  _content_tokens,
  _iter_todos_in_chunk,
  find_todos,
  format_todos_text,
)


class FakeCollection:
  def __init__(self, ids, docs, metas):
    self.ids = ids
    self.docs = docs
    self.metas = metas

  def get(self, *, limit, include, where=None):
    if where is None:
      filt = lambda m: True  # noqa: E731
    else:
      def filt(m):
        return all(m.get(k) == v for k, v in where.items())

    out_ids, out_docs, out_metas = [], [], []
    for i, cid in enumerate(self.ids):
      meta = self.metas[i]
      if not filt(meta):
        continue
      out_ids.append(cid)
      out_docs.append(self.docs[i])
      out_metas.append(meta)
      if len(out_ids) >= limit:
        break
    return {"ids": out_ids, "documents": out_docs, "metadatas": out_metas}


class FakeStore:
  def __init__(self, ids, docs, metas):
    self.collection = FakeCollection(ids, docs, metas)


def _store(*chunks):
  ids, docs, metas = [], [], []
  for cid, sid, proj, content, ts, src in chunks:
    ids.append(cid)
    docs.append(content)
    metas.append({
      "session_id": sid,
      "project": proj,
      "timestamp": ts,
      "source": src,
    })
  return FakeStore(ids, docs, metas)


def _rec(content: str, cid="c1", proj="proj-a", ts="2026-01-01T00:00:00Z"):
  return _ChunkRecord(
    cid=cid, content=content, session_id="s1",
    project=proj, source="claude-code", timestamp=ts,
  )


# ---------- detection ----------

def test_detects_todo_marker():
  todos = list(_iter_todos_in_chunk(_rec("TODO: refactor the auth middleware later.")))
  assert len(todos) == 1
  assert "refactor" in todos[0].text.lower()


def test_detects_fixme():
  todos = list(_iter_todos_in_chunk(_rec("FIXME: handle the empty array case in parser")))
  assert len(todos) == 1
  assert "parser" in todos[0].text.lower()


def test_detects_we_should():
  todos = list(_iter_todos_in_chunk(_rec("we should add retry logic to the upload flow.")))
  assert len(todos) == 1
  assert "retry" in todos[0].text.lower()


def test_detects_come_back_to():
  rec = _rec("I'll come back to the caching layer once Redis is set up.")
  todos = list(_iter_todos_in_chunk(rec))
  assert len(todos) == 1
  assert "caching" in todos[0].text.lower()


def test_detects_lets_add():
  todos = list(_iter_todos_in_chunk(_rec("let's add observability around the queue workers.")))
  assert len(todos) == 1


def test_detects_would_be_nice():
  todos = list(_iter_todos_in_chunk(_rec("would be nice to support websocket reconnect.")))
  assert len(todos) == 1


def test_ignores_normal_chatter():
  rec = _rec("the dashboard is rendering correctly now and tests pass.")
  todos = list(_iter_todos_in_chunk(rec))
  assert todos == []


def test_dedupes_within_chunk():
  """Same TODO matched by two patterns shouldn't double-count."""
  content = (
    "TODO: add observability around the queue workers.\n"
    "we should add observability around the queue workers."
  )
  todos = list(_iter_todos_in_chunk(_rec(content)))
  # 0.7 Jaccard threshold should collapse these.
  assert len(todos) == 1


def test_drops_thin_bodies():
  # "later." → no content tokens after stopword filter → skipped.
  todos = list(_iter_todos_in_chunk(_rec("TODO: later.")))
  assert todos == []


# ---------- content tokens ----------

def test_content_tokens_strips_stopwords():
  tokens = _content_tokens("we should refactor the auth middleware")
  assert "refactor" in tokens
  assert "auth" in tokens
  assert "middleware" in tokens
  assert "the" not in tokens
  assert "we" not in tokens
  assert "should" not in tokens


# ---------- resolution heuristic ----------

def test_resolution_marks_done_when_later_chunk_says_added():
  store = _store(
    ("c1", "s1", "proj-a",
     "we should add retry logic to the upload flow",
     "2026-01-01T00:00:00Z", "claude-code"),
    ("c2", "s2", "proj-a",
     "added retry logic to the upload flow today",
     "2026-02-01T00:00:00Z", "claude-code"),
  )
  out = find_todos(store)
  assert len(out) == 1
  assert out[0].resolved is True
  assert out[0].resolved_by_chunk == "c2"


def test_resolution_requires_later_timestamp():
  """A done-flavor mention BEFORE the TODO doesn't resolve it."""
  store = _store(
    ("c_done", "s0", "proj-a",
     "added retry logic to the upload flow",
     "2026-01-01T00:00:00Z", "claude-code"),
    ("c_todo", "s1", "proj-a",
     "we should add retry logic to the upload flow",
     "2026-02-01T00:00:00Z", "claude-code"),
  )
  out = find_todos(store)
  assert len(out) == 1
  assert out[0].resolved is False


def test_resolution_requires_same_project():
  store = _store(
    ("c1", "s1", "proj-a",
     "we should add retry logic to upload flow",
     "2026-01-01T00:00:00Z", "claude-code"),
    ("c2", "s2", "proj-b",
     "added retry logic to upload flow today",
     "2026-02-01T00:00:00Z", "claude-code"),
  )
  out = find_todos(store)
  assert len(out) == 1
  assert out[0].resolved is False


def test_resolution_requires_token_overlap():
  """A 'done' mention about an unrelated thing doesn't resolve the TODO."""
  store = _store(
    ("c1", "s1", "proj-a",
     "we should add retry logic to upload flow",
     "2026-01-01T00:00:00Z", "claude-code"),
    ("c2", "s2", "proj-a",
     "fixed the typo in the README",
     "2026-02-01T00:00:00Z", "claude-code"),
  )
  out = find_todos(store)
  assert out[0].resolved is False


# ---------- find_todos behavior ----------

def test_find_todos_empty_store():
  assert find_todos(_store()) == []


def test_find_todos_project_filter():
  store = _store(
    ("c1", "s1", "proj-a",
     "we should add retry logic to upload",
     "2026-01-01T00:00:00Z", "claude-code"),
    ("c2", "s2", "proj-b",
     "TODO: drop the legacy ORM helper",
     "2026-01-02T00:00:00Z", "claude-code"),
  )
  out = find_todos(store, project="proj-a")
  assert len(out) == 1
  assert out[0].project == "proj-a"


def test_only_unresolved_filter():
  store = _store(
    ("c1", "s1", "proj-a",
     "we should add retry logic to upload flow",
     "2026-01-01T00:00:00Z", "claude-code"),
    ("c2", "s2", "proj-a",
     "added retry logic to upload flow today",
     "2026-02-01T00:00:00Z", "claude-code"),
    ("c3", "s3", "proj-a",
     "FIXME: drop the legacy ORM helper class",
     "2026-03-01T00:00:00Z", "claude-code"),
  )
  all_todos = find_todos(store)
  unresolved = find_todos(store, only_unresolved=True)
  assert len(all_todos) == 2
  assert len(unresolved) == 1
  assert unresolved[0].resolved is False


def test_results_sorted_newest_first():
  store = _store(
    ("c1", "s1", "proj-a",
     "TODO: implement caching layer",
     "2026-01-01T00:00:00Z", "claude-code"),
    ("c2", "s2", "proj-a",
     "TODO: rewrite the upload endpoint",
     "2026-04-01T00:00:00Z", "claude-code"),
  )
  out = find_todos(store)
  assert out[0].timestamp == "2026-04-01T00:00:00Z"
  assert out[1].timestamp == "2026-01-01T00:00:00Z"


# ---------- formatting ----------

def test_format_todos_text_empty():
  assert "No TODOs" in format_todos_text([])


def test_format_todos_text_renders():
  store = _store(
    ("c1", "s1", "proj-a",
     "we should add retry logic to upload flow",
     "2026-01-01T00:00:00Z", "claude-code"),
    ("c2", "s2", "proj-a",
     "added retry logic to upload flow today",
     "2026-02-01T00:00:00Z", "claude-code"),
  )
  out = find_todos(store)
  text = format_todos_text(out)
  assert "1 open, 0 resolved" not in text  # this case: 0 open, 1 done
  assert "0 open" in text
  assert "1 resolved" in text
  assert "done" in text
