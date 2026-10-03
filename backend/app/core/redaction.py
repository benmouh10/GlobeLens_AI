"""
GlobeLens AI — Secret redaction helpers.

Centralises the rules used to keep credentials out of logs and out of any
object ``repr``. Two things are masked:

* values whose field name looks sensitive (``SECRET_KEY``, ``*_PASSWORD``,
  ``*_TOKEN``, ``*_API_KEY`` ...), and
* credentials embedded in URLs (``scheme://user:pass@host``), which covers
  ``DATABASE_URL`` / ``REDIS_URL`` even though their names are not sensitive.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

MASK = "***REDACTED***"

_SENSITIVE_KEY_RE = re.compile(
    r"(secret|passwd|password|pwd|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|client[_-]?secret|authorization|credential|vapid[_-]?private)",
    re.IGNORECASE,
)

_URL_CREDENTIALS_RE = re.compile(
    r"(?P<scheme>[a-z][a-z0-9+.\-]*://)(?P<user>[^:/?#@\s]+):(?P<pw>[^@/?#\s]+)@",
    re.IGNORECASE,
)


def is_sensitive_key(key: str) -> bool:
    """True when a field name suggests its value is a secret."""
    return bool(_SENSITIVE_KEY_RE.search(str(key or "")))


def mask_url_credentials(value: str) -> str:
    """Replace the password in any ``scheme://user:password@host`` with a mask."""
    return _URL_CREDENTIALS_RE.sub(
        lambda m: f"{m.group('scheme')}{m.group('user')}:{MASK}@", value
    )


def redact_value(key: str, value: Any) -> Any:
    """Recursively redact a single value, keeping its parent key for context."""
    if isinstance(value, Mapping):
        return {k: redact_value(k, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(key, v) for v in value]
    if isinstance(value, str):
        value = mask_url_credentials(value)
        # An unset secret stays empty rather than claiming a value is present.
        if value and is_sensitive_key(key):
            return MASK
        return value
    return value


def redact_mapping(data: Mapping[str, Any]) -> dict:
    """Return a copy of ``data`` with sensitive keys/values masked."""
    return {k: redact_value(k, v) for k, v in data.items()}


def redact_processor(logger: Any, method_name: str, event_dict: dict) -> dict:
    """structlog processor that redacts secrets from every log event."""
    return redact_mapping(event_dict)
