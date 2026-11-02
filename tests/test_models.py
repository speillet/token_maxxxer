from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from token_maxxxer.models import Attempt, ExecutionState, Task, UsageObservation


@pytest.mark.parametrize("task_id", ["../escape", "-option", "with space", "UPPER", "x" * 65])
def test_task_ids_cannot_escape_workspace(task, task_id) -> None:
    with pytest.raises(ValidationError):
        Task.model_validate({**task.model_dump(), "id": task_id})


@pytest.mark.parametrize("commands", [["python -m pytest"], [[]], [["python", "bad\x00argument"]]])
def test_commands_must_be_argument_arrays(task, commands) -> None:
    with pytest.raises(ValidationError):
        Task.model_validate({**task.model_dump(), "verification_commands": commands})


def test_command_arguments_are_preserved(task) -> None:
    commands = [["python", "-c", " print('space matters') "]]
    parsed = Task.model_validate({**task.model_dump(), "verification_commands": commands})
    assert parsed.verification_commands[0][2] == commands[0][2]


def test_usage_unknown_is_distinct_from_zero() -> None:
    now = datetime.now(UTC)
    assert UsageObservation(observed_at=now, source="cli").input_tokens is None
    assert UsageObservation(observed_at=now, source="cli", input_tokens=0).input_tokens == 0


def test_persisted_timestamps_are_aware_and_normalized_to_utc() -> None:
    local = datetime(2026, 11, 2, 22, tzinfo=timezone(timedelta(hours=1)))
    attempt = Attempt(task_id="demo", started_at=local)
    assert attempt.started_at == datetime(2026, 11, 2, 21, tzinfo=UTC)
    assert attempt.started_at.tzinfo == UTC
    with pytest.raises(ValidationError):
        Attempt(task_id="demo", started_at=datetime(2026, 11, 2))
    with pytest.raises(ValidationError):
        Attempt(task_id="demo", started_at=local, finished_at=local - timedelta(seconds=1))


def test_execution_state_schema_is_versioned() -> None:
    assert ExecutionState().schema_version == 1
    with pytest.raises(ValidationError):
        ExecutionState.model_validate({"schema_version": 2})
