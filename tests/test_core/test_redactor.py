"""Tests for the secret redaction layer."""

from agentvault.core.redactor import redact_secrets, is_sensitive_file


def test_redact_aws_key():
  text = "My key is AKIAIOSFODNN7EXAMPLE and it works"
  result = redact_secrets(text)
  assert "AKIAIOSFODNN7EXAMPLE" not in result
  assert "[REDACTED]" in result


def test_redact_github_token():
  text = "token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmn"
  result = redact_secrets(text)
  assert "ghp_" not in result
  assert "[REDACTED]" in result


def test_redact_openai_key():
  text = "OPENAI_API_KEY=sk-1234567890abcdefghijklmnop"
  result = redact_secrets(text)
  assert "sk-1234567890" not in result


def test_redact_bearer_token():
  text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.test.signature"
  result = redact_secrets(text)
  assert "eyJhbGciOiJIUzI1NiJ9" not in result


def test_redact_connection_string():
  text = "DATABASE_URL=postgres://user:password123@localhost:5432/db"
  result = redact_secrets(text)
  assert "password123" not in result


def test_redact_private_key():
  text = "-----BEGIN RSA PRIVATE KEY----- should be hidden"
  result = redact_secrets(text)
  assert "BEGIN RSA PRIVATE KEY" not in result


def test_redact_password_assignment():
  text = 'password = "supersecret123"'
  result = redact_secrets(text)
  assert "supersecret123" not in result


def test_no_false_positive_on_normal_text():
  text = "We decided to use PostgreSQL for the database because of concurrent writes."
  result = redact_secrets(text)
  assert result == text


def test_is_sensitive_file():
  assert is_sensitive_file(".env") is True
  assert is_sensitive_file(".env.production") is True
  assert is_sensitive_file("credentials.json") is True
  assert is_sensitive_file("server.key") is True
  assert is_sensitive_file("cert.pem") is True
  assert is_sensitive_file("service.account.json") is True
  assert is_sensitive_file("src/main.py") is False
  assert is_sensitive_file("README.md") is False
