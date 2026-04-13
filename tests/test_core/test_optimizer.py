"""Tests for token optimization."""

from agentvault.core.optimizer import (
  compact_metadata,
  dedup_results,
  optimize_content,
  strip_tool_noise,
  truncate_code_blocks,
)


def test_strip_tool_noise():
  text = """**User**: Fix the auth bug

**Assistant**: [Used tools: Read]
[Tools used: Read]

**Assistant**: I found the issue in the middleware."""
  result = strip_tool_noise(text)
  assert "[Used tools: Read]" not in result
  assert "[Tools used: Read]" not in result
  assert "I found the issue" in result


def test_strip_tool_keeps_content():
  text = "Here is how to use the tool:\nStep 1: configure it"
  result = strip_tool_noise(text)
  assert result == text


def test_truncate_code_blocks():
  text = """Here's the code:
```python
line 1
line 2
line 3
line 4
line 5
line 6
line 7
line 8
```
That's it."""
  result = truncate_code_blocks(text, max_lines=3)
  assert "line 1" in result
  assert "line 3" in result
  assert "line 8" not in result
  assert "truncated" in result


def test_truncate_short_code_blocks():
  text = """```
short code
```"""
  result = truncate_code_blocks(text, max_lines=4)
  assert "short code" in result
  assert "truncated" not in result


def test_dedup_results():
  # Same prefix (>100 chars) = deduped. Different prefix = kept.
  long_prefix = "We decided to use Clerk for authentication because it has better DX and pricing scales well for our use case and the team agreed"
  results = [
    {"content": long_prefix + " in the meeting.", "metadata": {}},
    {"content": long_prefix + " last Tuesday.", "metadata": {}},
    {"content": "Something completely different about database", "metadata": {}},
  ]
  unique = dedup_results(results)
  assert len(unique) == 2


def test_dedup_empty():
  assert dedup_results([]) == []


def test_compact_metadata():
  meta = {
    "project": "my-app",
    "source": "claude-code",
    "git_branch": "main",
    "timestamp": "2026-04-01T10:00:00Z",
  }
  result = compact_metadata(meta)
  assert "my-app" in result
  assert "claude-code" in result
  assert "main" in result
  assert "2026-04-01" in result


def test_compact_metadata_no_branch():
  meta = {
    "project": "my-app",
    "source": "cursor",
    "git_branch": "",
    "timestamp": "2026-04-01T10:00:00Z",
  }
  result = compact_metadata(meta)
  assert "my-app" in result
  assert "main" not in result


def test_optimize_content_full():
  text = """**Assistant**: [Used tools: Read]
[Tools used: Read]

**Assistant**: Here's the fix:

```python
import os
import sys
import json
import pathlib
import datetime
import collections
import itertools
import functools
```

Done."""
  result = optimize_content(text)
  assert "[Used tools:" not in result
  assert "[Tools used:" not in result
  assert "import os" in result
  assert "import functools" not in result  # truncated
  assert "truncated" in result


def test_optimize_removes_excess_blank_lines():
  text = "line 1\n\n\n\n\nline 2"
  result = optimize_content(text)
  assert "\n\n\n" not in result
  assert "line 1" in result
  assert "line 2" in result
