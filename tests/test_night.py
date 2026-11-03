import json
import subprocess
import sys
import time

import pytest
from pydantic import SecretStr

from token_maxxxer.config import ProviderConfig
from token_maxxxer.models import UsageObservation, utc_now
from token_maxxxer.night import NightPlan, _repository_lock, list_sessions, load_session, run_night
from token_maxxxer.results import GenerationResult
from token_maxxxer.skills import discover_skills, select_skill


class ScriptedProvider:
    def __init__(self, *actions):
        self.actions = iter(actions)
        self.requests = []

    def generate(self, request, credential):
        self.requests.append(request)
        action = next(self.actions)
        if isinstance(action, BaseException):
            raise action
        if isinstance(action, GenerationResult):
            return action
        return GenerationResult(
            status="success",
            text=json.dumps({"action": action}),
            usage=UsageObservation(
                observed_at=utc_now(), source="fixture", input_tokens=10, output_tokens=5
            ),
        )


def plan_for(repository, **changes) -> NightPlan:
    return NightPlan(
        repository=repository,
        skill="builtin:improve-code",
        provider=ProviderConfig(model="fixture-model"),
        interval_seconds=0,
        **changes,
    )


def execute(repository, tmp_path, provider, **changes):
    plan = plan_for(repository, **changes)
    skill = select_skill(discover_skills(repository), plan.skill, mode=plan.mode)
    return run_night(plan, skill, tmp_path / "state", provider, SecretStr("sk-fixture-value"))


def test_complete_edit_session_is_isolated_verified_and_inspectable(repository, tmp_path) -> None:
    original = (repository / "main.py").read_bytes()
    original_head = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"])
    provider = ScriptedProvider(
        {"type": "read_file", "path": "main.py"},
        {"type": "write_file", "path": "main.py", "content": "print('improved')\n"},
        {"type": "finish", "summary": "Improve the greeting.", "continue_work": False},
    )
    session = execute(
        repository,
        tmp_path,
        provider,
        verification_commands=(
            (
                sys.executable,
                "-c",
                "from pathlib import Path; assert 'improved' in Path('main.py').read_text()",
            ),
        ),
    )
    assert session.state == "completed"
    assert session.reason == "skill_completed"
    assert session.calls == 3
    assert session.observed_input_tokens == 30
    assert session.observed_output_tokens == 15
    assert session.verification[0]["status"] == "passed"
    assert (repository / "main.py").read_bytes() == original
    assert (
        subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"])
        == original_head
    )
    assert (session.worktree / "main.py").read_text() == "print('improved')\n"
    assert session.changed_files == ["main.py"]
    directory = tmp_path / "state/runs" / session.id
    assert load_session(directory) == session
    assert list_sessions(tmp_path / "state")[0] == session
    report = (directory / "report.md").read_text()
    assert "needs_review" in report
    assert "sk-fixture-value" not in (directory / "session.json").read_text()
    assert "Keep changes focused" in provider.requests[0].prompt


def test_review_mode_and_repeated_cycles_stop_at_call_limit(repository, tmp_path) -> None:
    provider = ScriptedProvider(
        *[
            {"type": "finish", "summary": f"Reviewed area {index}.", "continue_work": True}
            for index in range(3)
        ]
    )
    session = execute(repository, tmp_path, provider, mode="review", max_calls=3)
    assert session.reason == "call_limit_reached"
    assert len(session.summaries) == 3
    assert session.worktree is None
    assert "Reviewed area 0" in provider.requests[1].prompt


def test_dirty_edit_repository_is_rejected_before_creating_session(repository, tmp_path) -> None:
    (repository / "main.py").write_text("Uncommitted user work.\n")
    with pytest.raises(ValueError, match="clean"):
        execute(repository, tmp_path, ScriptedProvider())
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize("status", ["auth_error", "rate_limited", "timeout", "transient_error"])
def test_api_failure_preserves_already_written_work(repository, tmp_path, status) -> None:
    provider = ScriptedProvider(
        {"type": "write_file", "path": "new.py", "content": "# Useful partial work.\n"},
        GenerationResult(status=status, error_code="fixture_failure"),
    )
    session = execute(repository, tmp_path, provider)
    assert session.state == "failed"
    assert session.reason == status
    assert session.calls == 2
    assert (session.worktree / "new.py").is_file()
    assert not (repository / "new.py").exists()


@pytest.mark.parametrize("failure", [KeyboardInterrupt(), RuntimeError("sk-fixture-private-value")])
def test_interruption_or_unexpected_failure_leaves_safe_records(
    repository, tmp_path, failure
) -> None:
    session = execute(repository, tmp_path, ScriptedProvider(failure))
    assert session.state in ("interrupted", "failed")
    directory = tmp_path / "state/runs" / session.id
    assert load_session(directory).finished_at is not None
    assert "sk-fixture-private-value" not in (directory / "session.json").read_text()


@pytest.mark.parametrize(
    "text",
    [
        '{"action":{"type":"shell","command":"touch owned"}}',
        '{"action":{},"action":{"type":"finish","summary":"Bad"}}',
        "```json\n{}\n```",
        '{"action":{"type":"finish","summary":"Bad","continue_work":"false"}}',
    ],
)
def test_invalid_action_protocol_stops_without_execution(repository, tmp_path, text) -> None:
    session = execute(
        repository, tmp_path, ScriptedProvider(GenerationResult(status="success", text=text))
    )
    assert session.reason == "invalid_skill_action"
    assert session.changed_files == []


def test_repeated_denied_tools_stop_and_do_not_escape_repository(repository, tmp_path) -> None:
    provider = ScriptedProvider(
        *[{"type": "write_file", "path": "../owned.txt", "content": "Untrusted."} for _ in range(3)]
    )
    session = execute(repository, tmp_path, provider)
    assert session.reason == "repeated_tool_denial"
    assert not (tmp_path / "owned.txt").exists()
    assert all(event.get("tool_denied") for event in session.events)


def test_no_tool_is_executed_after_deadline_even_if_provider_returns_action(
    repository, tmp_path
) -> None:
    ticks = [0.0]

    class SlowProvider:
        def generate(self, request, credential):
            ticks[0] = 3601
            return GenerationResult(
                status="success",
                text=json.dumps(
                    {"action": {"type": "write_file", "path": "late.py", "content": "Too late."}}
                ),
            )

    plan = plan_for(repository, hours=1)
    skill = select_skill(discover_skills(repository), plan.skill, mode="edit")
    session = run_night(
        plan,
        skill,
        tmp_path / "state",
        SlowProvider(),
        SecretStr("fixture"),
        clock=lambda: ticks[0],
    )
    assert session.reason == "deadline_reached"
    assert not (session.worktree / "late.py").exists()


def test_wall_clock_deadline_interrupts_a_blocked_provider(repository, tmp_path) -> None:
    class BlockedProvider:
        def generate(self, request, credential):
            time.sleep(10)
            raise AssertionError("deadline must interrupt the provider")

    started = time.monotonic()
    session = execute(repository, tmp_path, BlockedProvider(), mode="review", hours=0.0001)
    assert session.reason == "deadline_reached"
    assert time.monotonic() - started < 3


def test_failed_verification_is_recorded_and_never_claims_success(repository, tmp_path) -> None:
    provider = ScriptedProvider(
        {"type": "write_file", "path": "new.py", "content": "# Candidate change.\n"},
        {"type": "finish", "summary": "Candidate change requires review."},
    )
    session = execute(
        repository,
        tmp_path,
        provider,
        verification_commands=((sys.executable, "-c", "raise SystemExit(1)"),),
    )
    assert session.verification[0]["status"] == "failed"
    assert session.worktree.is_dir()
    report = tmp_path / "state/runs" / session.id / "report.md"
    assert "needs_review" in report.read_text()


def test_repository_lock_prevents_duplicate_launches_across_state_directories(
    repository, tmp_path
) -> None:
    provider = ScriptedProvider()
    with _repository_lock(repository), pytest.raises(ValueError, match="another"):
        execute(repository, tmp_path, provider)
    assert provider.requests == []
    assert not (tmp_path / "state/runs").exists()


def test_checks_can_fail_then_be_fixed_in_the_same_cycle(repository, tmp_path) -> None:
    provider = ScriptedProvider(
        {"type": "write_file", "path": "candidate.py", "content": "broken\n"},
        {"type": "run_checks"},
        {"type": "write_file", "path": "candidate.py", "content": "fixed\n"},
        {"type": "run_checks"},
        {"type": "finish", "summary": "Corrected the failing check."},
    )
    session = execute(
        repository,
        tmp_path,
        provider,
        verification_commands=(
            (
                sys.executable,
                "-c",
                "from pathlib import Path; assert Path('candidate.py').read_text() == 'fixed\\n'",
            ),
        ),
    )
    assert [result["status"] for result in session.verification] == ["failed", "passed"]
    assert '"status": "failed"' in provider.requests[2].prompt


def test_interval_stops_at_deadline_instead_of_launching_another_cycle(
    repository, tmp_path
) -> None:
    now = [0.0]
    provider = ScriptedProvider(
        {"type": "finish", "summary": "One area reviewed.", "continue_work": True}
    )
    plan = plan_for(repository, mode="review", hours=0.001).model_copy(
        update={"interval_seconds": 60}
    )
    skill = select_skill(discover_skills(repository), plan.skill, mode="review")
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    session = run_night(
        plan,
        skill,
        tmp_path / "state",
        provider,
        SecretStr("fixture"),
        clock=lambda: now[0],
        sleep=sleep,
    )
    assert sleeps == [3.6]
    assert session.calls == 1
    assert session.reason == "deadline_reached"


def test_absolute_deadline_includes_time_spent_journaling_before_api_access(
    repository, tmp_path, monkeypatch
) -> None:
    import token_maxxxer.night as night

    now = [0.0]
    save = night._save

    def slow_save(session, directory):
        if session.events and session.events[-1].get("state") == "requesting":
            now[0] = 2
        save(session, directory)

    monkeypatch.setattr(night, "_save", slow_save)
    plan = plan_for(repository)
    skill = select_skill(discover_skills(repository), plan.skill, mode="edit")
    provider = ScriptedProvider()
    session = run_night(
        plan,
        skill,
        tmp_path / "state",
        provider,
        SecretStr("fixture"),
        clock=lambda: now[0],
        stop_at=1,
    )
    assert provider.requests == []
    assert session.reason == "deadline_reached"
    assert session.events[-1]["state"] == "skipped_deadline"
