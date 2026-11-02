import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from token_maxxxer.authentication import API_CONFIGURATION_VARIABLES
from token_maxxxer.claude_runner import (
    CliQualification,
    FakeClaudeRunner,
    RunRequest,
    SubprocessClaudeRunner,
)
from token_maxxxer.runner_result import RunnerResult

SCRIPT = Path(__file__).parent / "helpers/fake_claude.py"


@pytest.fixture
def request_data(tmp_path) -> RunRequest:
    return RunRequest(task_id="demo", workspace=tmp_path, prompt="Consigne explicite.")


@pytest.fixture
def qualification(tmp_path) -> CliQualification:
    return CliQualification(
        version="2.1.999",
        workspace=tmp_path,
        subscription_verified=True,
        extra_usage_disabled=True,
        settings_and_repository_audited=True,
    )


def runner(qualification, case="success", **environment) -> SubprocessClaudeRunner:
    return SubprocessClaudeRunner(
        qualification=qualification,
        command=(sys.executable, str(SCRIPT)),
        environment={"FIXTURE_CASE": case, **environment},
    )


def calls(workspace) -> list:
    return [json.loads(line) for line in (workspace / "calls.jsonl").read_text().splitlines()]


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("success", "success"),
        ("rate_limited", "rate_limited"),
        ("auth_error", "auth_error"),
        ("transient_error", "transient_error"),
        ("internal_error", "invalid_output"),
        ("malformed", "invalid_output"),
        ("invalid_encoding", "invalid_output"),
        ("crash", "invalid_output"),
    ],
)
def test_real_transport_with_offline_cli(qualification, request_data, case, expected) -> None:
    result = runner(qualification, case).run(request_data)
    assert result.status == expected
    # Version + metadata + exactly one attempt. No retry is hidden in the transport.
    assert len(calls(request_data.workspace)) == 3
    assert result.duration_seconds >= 0
    assert "private@example.invalid" not in result.model_dump_json()
    assert "private-fixture-token" not in result.model_dump_json()


def test_prompt_stdin_permissions_and_literal_arguments(qualification, request_data) -> None:
    marker = request_data.workspace / "must-not-exist"
    prompt = f"$(touch {marker}) `touch {marker}`; Unicode é"
    request_data = RunRequest(
        task_id="demo",
        workspace=request_data.workspace,
        prompt=prompt,
        allowed_tools=("Read", "Edit"),
        max_turns=2,
    )
    result = runner(qualification, "echo").run(request_data)
    assert result.text == prompt
    invocation = calls(request_data.workspace)[-1]
    assert prompt not in invocation
    assert invocation[invocation.index("--tools") + 1] == "Read,Edit"
    assert invocation[invocation.index("--allowedTools") + 1] == "Read,Edit"
    assert invocation[invocation.index("--permission-mode") + 1] == "dontAsk"
    assert invocation[invocation.index("--permission-prompts") + 1] == "none"
    assert invocation[invocation.index("--max-turns") + 1] == "2"
    assert "--strict-mcp-config" in invocation
    assert "--dangerously-skip-permissions" not in invocation
    assert "--bare" not in invocation
    assert not marker.exists()


def test_empty_tool_allowlist_does_not_enable_defaults(qualification, request_data) -> None:
    assert runner(qualification).run(request_data).status == "success"
    invocation = calls(request_data.workspace)[-1]
    assert invocation[invocation.index("--tools") + 1] == ""
    assert "--allowedTools" not in invocation
    assert invocation[invocation.index("--disallowedTools") + 1] == "mcp__*"


def test_timeout_is_not_retried(qualification, request_data) -> None:
    request_data = request_data.model_copy(update={"timeout_seconds": 0.3})
    result = runner(qualification, "timeout").run(request_data)
    assert result.status == "timeout"
    assert result.duration_seconds < 3
    assert len(calls(request_data.workspace)) == 3


@pytest.mark.parametrize("variable", API_CONFIGURATION_VARIABLES)
def test_incompatible_auth_environment_is_refused_before_any_process(
    qualification,
    request_data,
    variable,
    monkeypatch,
) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("must not launch a subprocess")

    monkeypatch.setattr("token_maxxxer.claude_runner.run_process", forbidden)
    result = runner(qualification, **{variable: "fixture-secret"}).run(request_data)
    assert result.status == "auth_error"
    assert "fixture-secret" not in result.model_dump_json()


@pytest.mark.parametrize("case", ["logged_out", "api_auth", "version_change"])
def test_preflight_failures_never_start_an_attempt(qualification, request_data, case) -> None:
    result = runner(qualification, case).run(request_data)
    assert result.status == ("invalid_output" if case == "version_change" else "auth_error")
    assert all("-p" not in invocation for invocation in calls(request_data.workspace))
    assert "private@example.invalid" not in result.model_dump_json()
    assert "private-fixture-token" not in result.model_dump_json()


def test_missing_qualification_and_different_workspace_never_launch(
    qualification,
    request_data,
    monkeypatch,
) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("must not launch a subprocess")

    monkeypatch.setattr("token_maxxxer.claude_runner.run_process", forbidden)
    assert SubprocessClaudeRunner().run(request_data).error_code == "qualification_required"
    different = qualification.model_copy(update={"workspace": request_data.workspace.parent})
    assert runner(different).run(request_data).error_code == "qualification_required"


def test_fake_is_deterministic_and_does_not_repeat_on_exhaustion(request_data) -> None:
    results = [RunnerResult(status="rate_limited"), RunnerResult(status="success", text="Done.")]
    fake = FakeClaudeRunner(results)
    assert fake.run(request_data) == results[0]
    assert fake.run(request_data) == results[1]
    with pytest.raises(RuntimeError, match="épuisé"):
        fake.run(request_data)
    assert fake.calls == [request_data, request_data]
    with pytest.raises(ValueError):
        FakeClaudeRunner([])


@pytest.mark.parametrize(
    "updates",
    [{"allowed_tools": ["*"]}, {"max_turns": 0}, {"timeout_seconds": 0}],
)
def test_request_bounds(request_data, updates) -> None:
    with pytest.raises(ValidationError):
        RunRequest.model_validate({**request_data.model_dump(), **updates})


def test_account_attestations_cannot_be_omitted_or_false(qualification) -> None:
    for field in (
        "subscription_verified",
        "extra_usage_disabled",
        "settings_and_repository_audited",
    ):
        with pytest.raises(ValidationError):
            CliQualification.model_validate({**qualification.model_dump(), field: False})
    with pytest.raises(ValidationError):
        CliQualification.model_validate({**qualification.model_dump(), "version": "2.1.1"})
