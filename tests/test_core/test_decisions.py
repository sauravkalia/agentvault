"""Tests for decision extraction."""

from agentvault.core.decisions import extract_decisions, format_decisions_markdown
from agentvault.core.schema import AgentSession, Exchange


def _make_session(content: str, role: str = "assistant"):
  return AgentSession(
    id="test-session",
    source="claude-code",
    project="test-project",
    started_at="2026-04-01T10:00:00Z",
    ended_at="2026-04-01T11:00:00Z",
    working_directory="/test",
    exchanges=[Exchange(role=role, content=content, timestamp="2026-04-01T10:00:00Z")],
  )


def test_extract_decided_to():
  session = _make_session("We decided to use Clerk for authentication.")
  decisions = extract_decisions(session)
  assert len(decisions) >= 1
  assert "Clerk" in decisions[0].text


def test_extract_going_with():
  session = _make_session("I recommend going with PostgreSQL over SQLite.")
  decisions = extract_decisions(session)
  assert len(decisions) >= 1
  assert "PostgreSQL" in decisions[0].text


def test_extract_chose_over():
  session = _make_session("We chose Redis over Memcached for the cache layer.")
  decisions = extract_decisions(session)
  assert len(decisions) >= 1
  assert "Redis" in decisions[0].text


def test_extract_switching_to():
  session = _make_session("We are switching to GraphQL from REST.")
  decisions = extract_decisions(session)
  assert len(decisions) >= 1
  assert "GraphQL" in decisions[0].text


def test_no_decisions():
  session = _make_session("Hello, how are you today?")
  decisions = extract_decisions(session)
  assert len(decisions) == 0


def test_deduplication():
  session = _make_session(
    "We decided to use Clerk. Yes, we decided to use Clerk for auth."
  )
  decisions = extract_decisions(session)
  # Should deduplicate similar decisions
  assert len(decisions) <= 2


def test_decision_metadata():
  session = _make_session("We decided to migrate to TypeScript.")
  decisions = extract_decisions(session)
  assert decisions[0].session_id == "test-session"
  assert decisions[0].project == "test-project"
  assert decisions[0].source == "claude-code"


def test_format_markdown():
  session = _make_session("We decided to use Vite over Webpack.")
  decisions = extract_decisions(session)
  md = format_decisions_markdown(decisions)
  assert "test-project" in md
  assert "claude-code" in md
  assert "Vite" in md


def test_format_empty():
  md = format_decisions_markdown([])
  assert md == ""
