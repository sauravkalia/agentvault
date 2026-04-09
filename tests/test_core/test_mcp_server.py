"""Tests for MCP server input validation."""

from agentvault.mcp_server import _validate_string, _validate_top_k, MAX_TOP_K


class TestValidateString:
  def test_normal_string(self):
    assert _validate_string("hello", "query") == "hello"

  def test_rejects_non_string(self):
    try:
      _validate_string(123, "query")
      assert False, "Should have raised ValueError"
    except ValueError as e:
      assert "must be a string" in str(e)

  def test_rejects_too_long(self):
    try:
      _validate_string("x" * 20000, "query")
      assert False, "Should have raised ValueError"
    except ValueError as e:
      assert "exceeds maximum length" in str(e)

  def test_respects_custom_max(self):
    try:
      _validate_string("x" * 300, "field", max_length=200)
      assert False, "Should have raised ValueError"
    except ValueError:
      pass

  def test_rejects_list(self):
    try:
      _validate_string(["a", "b"], "query")
      assert False, "Should have raised ValueError"
    except ValueError:
      pass


class TestValidateTopK:
  def test_default(self):
    assert _validate_top_k(None) == 5

  def test_normal_value(self):
    assert _validate_top_k(10) == 10

  def test_capped_at_max(self):
    assert _validate_top_k(999) == MAX_TOP_K

  def test_minimum_is_1(self):
    assert _validate_top_k(-5) == 1
    assert _validate_top_k(0) == 1

  def test_string_fallback(self):
    assert _validate_top_k("not a number") == 5

  def test_float_converted(self):
    assert _validate_top_k(3.7) == 3
