"""Shared API generation results with redacted public diagnostics."""

from typing import Annotated, Literal

from pydantic import Field, field_validator

from token_maxxxer.models import Model, UsageObservation
from token_maxxxer.redaction import redact

GenerationStatus = Literal[
    "success",
    "rate_limited",
    "quota_exhausted",
    "auth_error",
    "timeout",
    "transient_error",
    "invalid_output",
]


class GenerationResult(Model):
    status: GenerationStatus
    response_id: str | None = None
    text: str | None = None
    error_code: str | None = None
    duration_seconds: Annotated[float, Field(ge=0)] = 0
    usage: UsageObservation | None = None
    provider: str | None = None
    model: str | None = None

    @field_validator("response_id", "text", "error_code", "provider", "model")
    @classmethod
    def redact_diagnostics(cls, value: str | None) -> str | None:
        # Redact API response text and identifiers before returning or serializing them.
        return redact(value) if value is not None else None
