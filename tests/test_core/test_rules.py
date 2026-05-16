"""Tests for the rule-suggestion detector."""

from agentvault.core.rules import (
  _content_tokens,
  _extract_directives,
  find_rules,
  format_rules_text,
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
      "session_id": sid, "project": proj,
      "timestamp": ts, "source": src,
    })
  return FakeStore(ids, docs, metas)


# ---------- directive extraction ----------

def test_detects_dont():
  matches = list(_extract_directives("Please don't add Co-Authored-By lines."))
  assert len(matches) == 1


def test_detects_never():
  matches = list(_extract_directives("Never use git push --force on main."))
  assert len(matches) == 1


def test_detects_always():
  matches = list(_extract_directives("Always run lint before suggesting commits."))
  assert len(matches) == 1


def test_detects_stop_doing():
  matches = list(_extract_directives("Stop doing trailing summary paragraphs."))
  assert len(matches) == 1


def test_detects_use_instead():
  matches = list(_extract_directives("Use named exports instead of default exports."))
  assert len(matches) == 1


def test_detects_prefer_over():
  matches = list(_extract_directives("Prefer functional patterns over class-based ones."))
  assert len(matches) == 1


def test_detects_make_sure():
  matches = list(_extract_directives("Make sure you cover the empty-array case."))
  assert len(matches) == 1


def test_ignores_normal_chatter():
  matches = list(_extract_directives("Here is the dashboard implementation."))
  assert matches == []


# ---------- content tokens ----------

def test_content_tokens_strips_stopwords():
  t = _content_tokens("don't add Co-Authored-By lines to commits")
  assert "co" in t or "Co" not in t  # tokenizer lowercases
  assert "authored" in t
  assert "commits" in t


# ---------- find_rules clustering ----------

def test_find_rules_requires_min_occurrences():
  store = _store(
    ("c1", "s1", "proj-a",
     "Please don't add Co-Authored-By to commits.",
     "2026-01-01T00:00:00Z", "claude-code"),
    ("c2", "s2", "proj-a",
     "Stop adding Co-Authored-By trailers to commits.",
     "2026-02-01T00:00:00Z", "claude-code"),
  )
  assert find_rules(store, min_occurrences=3) == []
  assert len(find_rules(store, min_occurrences=2)) == 1


def test_find_rules_clusters_across_sessions():
  store = _store(
    ("c1", "s1", "proj-a",
     "don't add Co-Authored-By lines to commits",
     "2026-01-01T00:00:00Z", "claude-code"),
    ("c2", "s2", "proj-a",
     "stop adding Co-Authored-By lines to commits please",
     "2026-02-01T00:00:00Z", "claude-code"),
    ("c3", "s3", "proj-a",
     "never include Co-Authored-By lines in commits",
     "2026-03-01T00:00:00Z", "claude-code"),
  )
  out = find_rules(store, min_occurrences=3)
  assert len(out) == 1
  assert out[0].occurrence_count == 3
  assert out[0].projects == {"proj-a"}


def test_find_rules_within_chunk_dedupe():
  """One chunk repeating the same rule still counts as one occurrence
  in that chunk's session — otherwise a single noisy chunk could fake
  a 3-session pattern."""
  store = _store(
    ("c1", "s1", "proj-a",
     "don't add Co-Authored-By to commits.\n"
     "really, never add Co-Authored-By to commits.",
     "2026-01-01T00:00:00Z", "claude-code"),
  )
  out = find_rules(store, min_occurrences=1)
  assert len(out) == 1
  assert out[0].occurrence_count == 1


def test_find_rules_project_filter():
  store = _store(
    ("c1", "s1", "proj-a",
     "don't add Co-Authored-By to commits.",
     "2026-01-01T00:00:00Z", "claude-code"),
    ("c2", "s2", "proj-a",
     "stop adding Co-Authored-By to commits.",
     "2026-02-01T00:00:00Z", "claude-code"),
    ("c3", "s3", "proj-a",
     "never include Co-Authored-By in commits.",
     "2026-03-01T00:00:00Z", "claude-code"),
    ("c4", "s4", "proj-b",
     "don't add Co-Authored-By to commits.",
     "2026-04-01T00:00:00Z", "claude-code"),
  )
  out = find_rules(store, project="proj-a", min_occurrences=3)
  assert len(out) == 1
  assert out[0].projects == {"proj-a"}


def test_find_rules_handles_empty_store():
  assert find_rules(_store()) == []


def test_find_rules_sort_order():
  # cluster A: 4 sessions, last 2026-02-01
  # cluster B: 4 sessions, last 2026-05-01 → should appear first
  chunks = []
  for s in range(4):
    chunks.append((
      f"a{s}", f"sa{s}", "p",
      "always run lint after code changes",
      f"2026-01-0{s + 1}T00:00:00Z", "c",
    ))
  for s in range(4):
    chunks.append((
      f"b{s}", f"sb{s}", "p",
      "never include co-authored-by trailers in commits",
      f"2026-04-0{s + 1}T00:00:00Z", "c",
    ))
  store = _store(*chunks)
  out = find_rules(store, min_occurrences=4)
  assert len(out) == 2
  assert out[0].last_seen.startswith("2026-04-04")


# ---------- formatting ----------

def test_format_rules_text_empty():
  assert "No repeated correction" in format_rules_text([])


def test_format_rules_text_renders():
  store = _store(
    ("c1", "s1", "proj-a",
     "don't add Co-Authored-By to commits.",
     "2026-01-01T00:00:00Z", "claude-code"),
    ("c2", "s2", "proj-a",
     "stop adding Co-Authored-By to commits.",
     "2026-02-01T00:00:00Z", "claude-code"),
    ("c3", "s3", "proj-a",
     "never include Co-Authored-By in commits.",
     "2026-03-01T00:00:00Z", "claude-code"),
  )
  out = find_rules(store, min_occurrences=3)
  text = format_rules_text(out)
  assert "3 sessions" in text
  assert "proj-a" in text
