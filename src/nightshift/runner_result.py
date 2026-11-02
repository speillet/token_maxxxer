"""Conservative normalization of Claude's terminal JSON, without text heuristics."""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nightshift.models import Model, NonNegativeInt, UsageObservation, utc_now
from nightshift.redaction import redact

RunnerStatus = Literal[
    "success",
    "rate_limited",
    "auth_error",
    "timeout",
    "transient_error",
    "invalid_output",
]


class RunnerResult(Model):
    status: RunnerStatus
    exit_code: int | None = None
    session_id: str | None = None
    text: str | None = None
    error_code: str | None = None
    stdout: str = Field(default="", repr=False)
    stderr: str = Field(default="", repr=False)
    duration_seconds: Annotated[float, Field(ge=0)] = 0
    usage: UsageObservation | None = None

    @field_validator("session_id", "text", "error_code", "stdout", "stderr")
    @classmethod
    def redact_diagnostics(cls, value: str | None) -> str | None:
        # Apply equally to real output and fixtures supplied to the fake runner.
        return redact(value) if value is not None else None


class _WireUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False, hide_input_in_errors=True)
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None


class _WireResult(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False, hide_input_in_errors=True)
    type: Literal["result"]
    subtype: str
    is_error: Annotated[bool, Field(strict=True)]
    session_id: Annotated[str, Field(min_length=1)] | None = None
    result: str | None = None
    errors: tuple[str, ...] | None = None
    api_error_status: Annotated[int, Field(strict=True, ge=100, le=599)] | None = None
    terminal_reason: str | None = None
    usage: _WireUsage | None = None
    total_cost_usd: Annotated[float, Field(strict=True, ge=0)] | None = None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def normalize_result(
    stdout: str,
    stderr: str,
    exit_code: int,
    *,
    duration_seconds: float = 0,
) -> RunnerResult:
    """Only a coherent terminal message plus exit 0 can mean runner success."""
    try:
        payload = json.loads(stdout, object_pairs_hook=_unique_object)
        wire = _WireResult.model_validate(payload)
    except (ValueError, RecursionError):
        return RunnerResult(
            status="invalid_output",
            exit_code=exit_code,
            error_code="invalid_terminal_json",
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration_seconds,
        )

    status: RunnerStatus = "invalid_output"
    error_code: str | None = "inconsistent_terminal_result"
    # Even subtype=success can carry is_error=true after an API failure.
    if wire.is_error:
        error_code = "unclassified_cli_error"
        if wire.api_error_status in (401, 403):
            status, error_code = "auth_error", "authentication_failed"
        elif wire.api_error_status == 429:
            status, error_code = "rate_limited", "usage_limit"
        elif wire.api_error_status == 408 or (
            wire.api_error_status is not None and wire.api_error_status >= 500
        ):
            status, error_code = "transient_error", "provider_unavailable"
    elif (
        exit_code == 0
        and wire.subtype == "success"
        and wire.result is not None
        and not wire.errors
        and wire.api_error_status is None
        and wire.terminal_reason != "api_error"
    ):
        status, error_code = "success", None

    usage = None
    if wire.usage is not None or wire.total_cost_usd is not None or status == "rate_limited":
        usage = UsageObservation(
            observed_at=utc_now(),
            source="claude_cli",
            input_tokens=wire.usage.input_tokens if wire.usage else None,
            output_tokens=wire.usage.output_tokens if wire.usage else None,
            estimated_cost_usd=wire.total_cost_usd,
            limit_reached=status == "rate_limited",
        )
    return RunnerResult(
        status=status,
        exit_code=exit_code,
        session_id=wire.session_id,
        text=wire.result,
        error_code=error_code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=duration_seconds,
        usage=usage,
    )
