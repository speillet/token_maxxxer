"""Redact common credential formats before returning process diagnostics."""

import re

_PROVIDER_KEY = re.compile(r"\bsk-(?:ant|proj)-[A-Za-z0-9_-]+")
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE)
_NAMED_SECRET = re.compile(
    r"(\b(?:api_key|access_token|refresh_token|client_secret|password)"
    r"[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+",
    re.IGNORECASE,
)


def redact(value: str) -> str:
    value = _PROVIDER_KEY.sub("[REDACTED]", value)
    value = _BEARER.sub("Bearer [REDACTED]", value)
    return _NAMED_SECRET.sub(r"\1[REDACTED]", value)
