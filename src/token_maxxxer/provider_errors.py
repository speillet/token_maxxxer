"""Classify provider failures without exposing their bodies or exception text."""

from token_maxxxer.results import GenerationStatus

_QUOTA_CODES = {
    "insufficient_quota",
    "quota_exhausted",
    "quota_exceeded",
    "usage_limit_reached",
    "billing_hard_limit_reached",
    "credit_balance_too_low",
    "premium_request_quota_exceeded",
}
_QUOTA_MESSAGES = (
    "credit balance is too low",
    "insufficient credits",
    "insufficient quota",
    "you've hit your usage limit",
    "you have hit your usage limit",
    "usage limit reached",
    "quota has been exceeded",
    "quota exceeded",
    "premium request limit",
    "premium request quota",
    "no remaining credits",
)


def classify_failure(
    code: object = None,
    message: object = "",
    http_status: int | None = None,
) -> tuple[GenerationStatus, str]:
    kind = code.lower() if isinstance(code, str) else ""
    text = message.lower() if isinstance(message, str) else ""
    if http_status in (401, 403) or kind in {"authentication_error", "auth_required"}:
        return "auth_error", "provider_authentication_failed"
    if kind in _QUOTA_CODES or (
        http_status in (None, 400, 402, 429)
        and any(fragment in text for fragment in _QUOTA_MESSAGES)
    ):
        return "quota_exhausted", "provider_quota_exhausted"
    if http_status == 429 or kind in {"rate_limit_error", "rate_limited"}:
        return "rate_limited", "provider_rate_limited"
    if http_status == 408 or (http_status is not None and http_status >= 500):
        return "transient_error", "provider_unavailable"
    return "invalid_output", "provider_request_failed"
