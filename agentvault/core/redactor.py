"""Secret redaction layer — scans text for common credential patterns."""

from __future__ import annotations

import re

# Patterns that indicate secrets — each tuple is (name, regex)
SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
  ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
  ("AWS Secret Key", re.compile(r"(?i)aws.{0,20}secret.{0,10}['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{40}")),
  ("GitHub Token", re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}")),
  ("GitLab Token", re.compile(r"glpat-[A-Za-z0-9\-]{20,}")),
  ("Slack Token", re.compile(r"xox[bporas]-[A-Za-z0-9\-]+")),
  ("OpenAI Key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
  ("Anthropic Key", re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}")),
  ("Generic API Key", re.compile(r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9\-_.]{20,}['\"]?")),
  ("Bearer Token", re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_.~+/]+=*")),
  ("Private Key Block", re.compile(r"-----BEGIN\s+(RSA\s+|EC\s+|DSA\s+|OPENSSH\s+)?PRIVATE KEY-----")),
  ("Connection String", re.compile(r"(?i)(mongodb(\+srv)?|postgres(ql)?|mysql|redis|amqp)://[^\s'\"]+")),
  ("Password in URL", re.compile(r"://[^:]+:[^@\s]+@")),
  ("Generic Secret Assign", re.compile(r"(?i)(password|passwd|secret|token)\s*[:=]\s*['\"]?[^\s'\"]{8,}['\"]?")),
  ("Base64 JWT", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
  ("Hex Secret (32+)", re.compile(r"(?i)(secret|key|token)\s*[:=]\s*['\"]?[0-9a-f]{32,}['\"]?")),
]

# Files that commonly contain secrets — skip tool call inputs for these
SENSITIVE_FILE_PATTERNS: list[re.Pattern] = [
  re.compile(r"\.env($|\.)"),
  re.compile(r"credentials"),
  re.compile(r"\.pem$"),
  re.compile(r"\.key$"),
  re.compile(r"\.p12$"),
  re.compile(r"\.pfx$"),
  re.compile(r"service.account"),
  re.compile(r"secret"),
]

REDACTED = "[REDACTED]"


def redact_secrets(text: str) -> str:
  """Replace detected secrets in text with [REDACTED]."""
  for name, pattern in SECRET_PATTERNS:
    text = pattern.sub(REDACTED, text)
  return text


def is_sensitive_file(file_path: str) -> bool:
  """Check if a file path matches known sensitive file patterns."""
  lower = file_path.lower()
  return any(p.search(lower) for p in SENSITIVE_FILE_PATTERNS)
