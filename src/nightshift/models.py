"""Validated domain objects shared by configuration, storage and future execution."""

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TaskId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
CommandArgument = Annotated[str, StringConstraints(min_length=1)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(UTC))]


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )


def resolve_path(value: Path, info: ValidationInfo) -> Path:
    """Resolve YAML paths against the source file, never the caller's working directory."""
    base = info.context.get("base_directory", Path.cwd()) if info.context else Path.cwd()
    return (base / value.expanduser()).resolve()


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_LIMIT = "waiting_limit"
    PAUSED_SCHEDULE = "paused_schedule"
    NEEDS_REVIEW = "needs_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(Model):
    id: TaskId
    repository: Path
    base_ref: Text
    prompt: Text
    priority: NonNegativeInt = 0
    acceptance_criteria: Annotated[tuple[Text, ...], Field(min_length=1)]
    verification_commands: tuple[
        Annotated[tuple[CommandArgument, ...], Field(min_length=1)], ...
    ] = ()

    _resolve_repository = field_validator("repository")(resolve_path)

    @field_validator("base_ref")
    @classmethod
    def safe_base_ref(cls, value: str) -> str:
        if value.startswith("-") or any(char.isspace() or ord(char) < 32 for char in value):
            raise ValueError(
                "base_ref doit être une référence Git explicite, sans option ni espace"
            )
        return value

    @field_validator("verification_commands")
    @classmethod
    def command_arguments(cls, value: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
        if any("\x00" in argument for command in value for argument in command):
            raise ValueError("les arguments de vérification ne peuvent pas contenir NUL")
        return value


class TaskRecord(Model):
    task: Task
    status: TaskStatus
    created_at: UtcDatetime


class Attempt(Model):
    id: UUID = Field(default_factory=uuid4)
    task_id: TaskId
    started_at: UtcDatetime
    finished_at: UtcDatetime | None = None
    status: Literal[
        "running",
        "success",
        "rate_limited",
        "auth_error",
        "timeout",
        "transient_error",
        "invalid_output",
        "interrupted",
    ] = "running"
    worktree: Path | None = None
    branch: Text | None = None
    session_id: Text | None = None
    result: dict[str, JsonValue] | None = None
    error: Text | None = None
    next_retry_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def chronological_dates(self) -> "Attempt":
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at doit suivre started_at")
        return self


class ExecutionState(Model):
    schema_version: Literal[1] = 1
    task_id: TaskId | None = None
    attempt_id: UUID | None = None
    phase: Literal[
        "selection",
        "preparation",
        "execution",
        "verification",
        "classification",
        "report",
        "paused",
    ] = "selection"
    window_deadline: UtcDatetime | None = None
    retry_count: NonNegativeInt = 0
    pause_reason: Text | None = None


class UsageObservation(Model):
    observed_at: UtcDatetime
    source: Text
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None
    estimated_cost_usd: Annotated[float, Field(ge=0)] | None = None
    limit_reached: bool = False
    resets_at: UtcDatetime | None = None


def utc_now() -> datetime:
    return datetime.now(UTC)
