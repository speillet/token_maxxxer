"""Redact common credential formats before returning process diagnostics."""

import json
import re

from nightshift.json_io import load_unique_json

_PROVIDER_KEY = re.compile(r"\bsk-(?:ant|proj)-[A-Za-z0-9_-]+")
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE)
_NAMED_SECRET = re.compile(
    r"((?<![a-z0-9])(?:api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|password|authorization)[\"']?\s*[:=]\s*).*",
    re.IGNORECASE | re.DOTALL,
)
_SECRET_NAME = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|password|authorization)$",
    re.IGNORECASE,
)


def _plain_text(value: str) -> str:
    value = _PROVIDER_KEY.sub("[REDACTED]", value)
    value = _BEARER.sub("Bearer [REDACTED]", value)
    # Discard the rest of credential-bearing text, including quoted line breaks.
    return _NAMED_SECRET.sub(r"\1[REDACTED]", value)


def _json_value(value: object) -> object:
    if isinstance(value, dict):
        return {
            _plain_text(key): "[REDACTED]" if _SECRET_NAME.search(key) else _json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return _plain_text(value) if isinstance(value, str) else value


def redact(value: str) -> str:
    try:
        decoded = load_unique_json(value)
        sanitized = _json_value(decoded)
        if sanitized != decoded:
            return json.dumps(sanitized, ensure_ascii=False)
    except (ValueError, RecursionError):
        return _plain_text(value)
    return value
