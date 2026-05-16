"""Tests for the recurring-problem detector."""

from agentvault.core.patterns import (
  _fingerprint,
  _is_problem_line,
  _iter_problem_signals,
  find_patterns,
  format_patterns_text,
)


class FakeCollection:
  """Minimal stand-in for chroma collection.get()."""

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
  """chunks: list of (id, session_id, project, content, ts, source)."""
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


# ---------- problem-line detection ----------

def test_is_problem_line_detects_error():
  assert _is_problem_line("got a TypeError on submit")


def test_is_problem_line_detects_doesnt_work():
  assert _is_problem_line("the auth flow doesn't work after deploy")


def test_is_problem_line_rejects_normal_chatter():
  assert not _is_problem_line("let's add a new endpoint for the dashboard")


def test_is_problem_line_curly_apostrophe():
  assert _is_problem_line("button doesn’t work on mobile")


# ---------- fingerprint ----------

def test_fingerprint_is_stable_across_word_order():
  fp_a = _fingerprint("redirect handling broken for login flow")
  fp_b = _fingerprint("login flow broken because redirect handling")
  assert fp_a == fp_b


def test_fingerprint_discriminates_different_topics():
  fp_a = _fingerprint("redirect handling broken in login flow")
  fp_b = _fingerprint("memory leak in worker process crashing")
  assert fp_a != fp_b


def test_fingerprint_strips_stopwords():
  fp = _fingerprint("the error is in the auth module")
  # 'the', 'is', 'in' should be removed
  assert "the" not in fp.split()
  assert "is" not in fp.split()


def test_fingerprint_returns_none_for_thin_content():
  # Only one content word after stopwords — too generic.
  assert _fingerprint("the error") is None


# ---------- iter_problem_signals ----------

def test_iter_problem_signals_pulls_relevant_lines():
  text = (
    "we discussed the new dashboard\n"
    "but the redirect handling is broken for the login flow\n"
    "shipped on Friday\n"
  )
  signals = list(_iter_problem_signals(text))
  assert len(signals) == 1
  line, fp = signals[0]
  assert "redirect" in line
  assert "redirect" in fp


# ---------- find_patterns clustering ----------

def test_find_patterns_requires_min_sessions():
  store = _store(
    ("c1", "s1", "proj-a",
     "the redirect handling is broken in the login flow", "2026-01-01", "claude-code"),
    ("c2", "s2", "proj-a",
     "another bug — redirect login broken handling flow again",
     "2026-01-02", "claude-code"),
  )
  # Only 2 sessions for the redirect cluster, default min_sessions=3 → empty.
  out = find_patterns(store, min_sessions=3)
  assert out == []

  out = find_patterns(store, min_sessions=2)
  assert len(out) == 1
  assert out[0].session_count == 2


def test_find_patterns_groups_across_sessions():
  store = _store(
    ("c1", "s1", "proj-a",
     "the redirect handling is broken in login flow", "2026-01-01", "claude-code"),
    ("c2", "s2", "proj-a",
     "redirect handling login flow broken again", "2026-02-01", "cursor"),
    ("c3", "s3", "proj-a",
     "broken login flow redirect handling", "2026-03-01", "claude-code"),
    ("c4", "s1", "proj-a",
     "memory leak in worker crashing the queue", "2026-01-05", "claude-code"),
  )
  out = find_patterns(store, min_sessions=3)
  assert len(out) == 1
  p = out[0]
  assert p.session_count == 3
  assert p.projects == {"proj-a"}
  assert p.sources == {"claude-code", "cursor"}
  assert p.first_seen == "2026-01-01"
  assert p.last_seen == "2026-03-01"


def test_find_patterns_dedupes_within_same_chunk():
  """The same fingerprint appearing twice in one chunk still counts as
  one occurrence in that chunk's session — otherwise a noisy chunk
  could fake a 3-session pattern by itself."""
  store = _store(
    ("c1", "s1", "proj-a",
     "redirect handling broken login flow\n"
     "again the redirect handling is broken on login flow",
     "2026-01-01", "claude-code"),
  )
  out = find_patterns(store, min_sessions=1)
  assert len(out) == 1
  assert out[0].session_count == 1


def test_find_patterns_project_filter():
  store = _store(
    ("c1", "s1", "proj-a",
     "broken redirect handling login flow", "2026-01-01", "claude-code"),
    ("c2", "s2", "proj-a",
     "broken redirect handling login flow again", "2026-02-01", "claude-code"),
    ("c3", "s3", "proj-a",
     "still broken redirect handling login flow", "2026-03-01", "claude-code"),
    ("c4", "s4", "proj-b",
     "broken redirect handling login flow elsewhere", "2026-01-01", "claude-code"),
  )
  out = find_patterns(store, project="proj-a", min_sessions=3)
  assert len(out) == 1
  assert out[0].projects == {"proj-a"}


def test_find_patterns_handles_empty_store():
  store = _store()
  assert find_patterns(store) == []


def test_find_patterns_sorts_by_session_count_then_recency():
  # cluster A: 4 sessions, latest 2026-02-01
  # cluster B: 4 sessions, latest 2026-05-01
  # → B should come first (ties on session count broken by recency)
  store = _store(
    ("a1", "sa1", "p", "redirect broken handling login flow", "2026-01-01", "c"),
    ("a2", "sa2", "p", "redirect broken handling login flow", "2026-01-15", "c"),
    ("a3", "sa3", "p", "redirect broken handling login flow", "2026-02-01", "c"),
    ("a4", "sa4", "p", "redirect broken handling login flow", "2026-02-01", "c"),
    ("b1", "sb1", "p", "memory leak crashing worker queue", "2026-04-01", "c"),
    ("b2", "sb2", "p", "memory leak crashing worker queue", "2026-04-15", "c"),
    ("b3", "sb3", "p", "memory leak crashing worker queue", "2026-04-20", "c"),
    ("b4", "sb4", "p", "memory leak crashing worker queue", "2026-05-01", "c"),
  )
  out = find_patterns(store, min_sessions=4)
  assert len(out) == 2
  assert out[0].last_seen == "2026-05-01"
  assert out[1].last_seen == "2026-02-01"


def test_find_patterns_top_n_cap():
  # 5 distinct clusters, each with 3 sessions.
  chunks = []
  cluster_words = [
    "redirect broken handling login flow",
    "memory leak crashing worker queue",
    "timeout fetching upstream api response",
    "null pointer encountered parser module",
    "exception thrown serializing payload buffer",
  ]
  for ci, words in enumerate(cluster_words):
    for s in range(3):
      chunks.append((f"c{ci}_{s}", f"s{ci}_{s}", "p", words, f"2026-0{ci+1}-01", "c"))
  store = _store(*chunks)
  out = find_patterns(store, min_sessions=3, top_n=2)
  assert len(out) == 2


# ---------- formatting ----------

def test_format_patterns_text_empty():
  assert "No recurring problems" in format_patterns_text([])


def test_format_patterns_text_renders_clusters():
  store = _store(
    ("c1", "s1", "proj-a",
     "redirect handling broken login flow", "2026-01-01", "claude-code"),
    ("c2", "s2", "proj-a",
     "redirect handling broken login flow", "2026-02-01", "claude-code"),
    ("c3", "s3", "proj-a",
     "redirect handling broken login flow", "2026-03-01", "claude-code"),
  )
  out = find_patterns(store, min_sessions=3)
  text = format_patterns_text(out)
  assert "3 sessions" in text
  assert "proj-a" in text
  assert "fingerprint:" in text
