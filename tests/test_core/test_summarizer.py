"""Tests for session summary generation."""

from agentvault.core.schema import AgentSession, Exchange, ToolCall
from agentvault.core.summarizer import generate_summary, _extract_keywords


def _make_session(exchanges=None, files=None):
  return AgentSession(
    id="test",
    source="claude-code",
    project="test-project",
    started_at="2026-04-01T10:00:00Z",
    ended_at="2026-04-01T11:00:00Z",
    working_directory="/test",
    exchanges=exchanges or [],
    files_touched=files or [],
  )


def test_extract_keywords():
  text = "authentication middleware OAuth token refresh endpoint"
  keywords = _extract_keywords(text)
  assert "authentication" in keywords or "middleware" in keywords
  assert len(keywords) <= 5


def test_empty_session():
  session = _make_session()
  summary = generate_summary(session)
  assert summary == "Empty session."


def test_basic_summary():
  session = _make_session(exchanges=[
    Exchange(role="human", content="How do I set up authentication?", timestamp=""),
    Exchange(role="assistant", content="Use Clerk for auth.", timestamp=""),
  ])
  summary = generate_summary(session)
  assert "2 exchanges" in summary
  assert "authentication" in summary.lower()


def test_summary_with_tools():
  session = _make_session(exchanges=[
    Exchange(role="human", content="Fix the database connection", timestamp=""),
    Exchange(
      role="assistant", content="Done.",
      timestamp="",
      tool_calls=[ToolCall(name="Edit", input={})],
    ),
  ])
  summary = generate_summary(session)
  assert "Edit" in summary


def test_summary_with_files():
  session = _make_session(
    exchanges=[
      Exchange(role="human", content="Update the config", timestamp=""),
      Exchange(role="assistant", content="Updated.", timestamp=""),
    ],
    files=["src/config.ts", "src/utils.ts", "package.json"],
  )
  summary = generate_summary(session)
  assert "3 files" in summary


def test_keywords_filter_stopwords():
  keywords = _extract_keywords("the is a an to of in for this that")
  assert len(keywords) == 0
