"""Claude transport and deterministic fake; not connected to real CLI task execution yet."""

import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import Field, field_validator

from token_maxxxer.authentication import API_CONFIGURATION_VARIABLES
from token_maxxxer.json_io import load_unique_json
from token_maxxxer.models import Model, TaskId, Text
from token_maxxxer.process import ProcessCapture, run_process
from token_maxxxer.runner_result import RunnerResult, RunnerStatus, normalize_result

Tool = Literal["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
CliVersion = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]


class RunRequest(Model):
    task_id: TaskId
    workspace: Path
    prompt: Text = Field(repr=False)
    allowed_tools: tuple[Tool, ...] = ()
    timeout_seconds: Annotated[float, Field(gt=0, le=86400)] = 1800
    max_turns: Annotated[int, Field(strict=True, ge=1, le=100)] = 10

    @field_validator("workspace")
    @classmethod
    def existing_workspace(cls, value: Path) -> Path:
        value = value.expanduser().resolve()
        if not value.is_dir():
            raise ValueError("le workspace doit être un répertoire existant")
        return value

    @field_validator("prompt")
    @classmethod
    def bounded_prompt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 10_000_000:
            raise ValueError("consigne trop volumineuse pour stdin")
        return value


class CliQualification(Model):
    """Explicit pilot attestations, bound to an audited workspace and an exact version.

    This is an integration gate, not a sandbox or automatic proof about account settings.
    No CLI command creates these attestations until the milestone 0 pilot is complete.
    """

    version: CliVersion
    workspace: Path
    subscription_verified: Literal[True]
    extra_usage_disabled: Literal[True]
    settings_and_repository_audited: Literal[True]

    @field_validator("version")
    @classmethod
    def supports_unattended_permissions(cls, value: str) -> str:
        if tuple(map(int, value.split("."))) < (2, 1, 259):
            raise ValueError("version trop ancienne pour --permission-prompts none")
        return value

    @field_validator("workspace")
    @classmethod
    def absolute_workspace(cls, value: Path) -> Path:
        return value.expanduser().resolve()


class ClaudeRunner(Protocol):
    def run(self, request: RunRequest) -> RunnerResult: ...


class FakeClaudeRunner:
    """Return one scripted result per call; exhaustion never repeats the last result."""

    def __init__(self, results: Sequence[RunnerResult]):
        if not results:
            raise ValueError("le scénario doit contenir au moins un résultat")
        self._results = iter(tuple(results))
        self.calls: list[RunRequest] = []

    def run(self, request: RunRequest) -> RunnerResult:
        try:
            result = next(self._results)
        except StopIteration as exc:
            raise RuntimeError("scénario du faux exécuteur épuisé") from exc
        self.calls.append(request)
        return result


def _capture_result(capture: ProcessCapture) -> RunnerResult:
    status: RunnerStatus
    if capture.timed_out:
        status, code = "timeout", "process_timeout"
    elif capture.output_exceeded:
        status, code = "invalid_output", "output_limit_exceeded"
    elif capture.invalid_encoding:
        status, code = "invalid_output", "invalid_output_encoding"
    elif capture.launch_failed:
        status, code = "invalid_output", "cli_unavailable"
    else:
        assert capture.exit_code is not None
        return normalize_result(
            capture.stdout,
            capture.stderr,
            capture.exit_code,
            duration_seconds=capture.duration_seconds,
        )
    return RunnerResult(
        status=status,
        error_code=code,
        exit_code=capture.exit_code,
        stdout=capture.stdout,
        stderr=capture.stderr,
        duration_seconds=capture.duration_seconds,
    )


class SubprocessClaudeRunner:
    """Perform one invocation after qualification and read-only auth/version checks.

    The caller owns worktree preparation and durable journaling. No retries, task-state
    updates, commits, merges or implicit session resume take place in this adapter.
    """

    def __init__(
        self,
        *,
        qualification: CliQualification | None = None,
        command: tuple[str, ...] = ("claude",),
        environment: Mapping[str, str] | None = None,
    ):
        if not command:
            raise ValueError("commande CLI vide")
        self._qualification = qualification
        self._command = command
        self._environment = dict(environment) if environment is not None else None

    def run(self, request: RunRequest) -> RunnerResult:
        qualification = self._qualification
        if qualification is None or qualification.workspace != request.workspace:
            return RunnerResult(status="invalid_output", error_code="qualification_required")
        environment = dict(os.environ if self._environment is None else self._environment)
        if any(environment.get(name) for name in API_CONFIGURATION_VARIABLES):
            return RunnerResult(
                status="auth_error", error_code="incompatible_authentication_environment"
            )
        version = run_process(
            [*self._command, "--version"],
            cwd=request.workspace,
            environment=environment,
            timeout_seconds=10,
            max_output_bytes=4096,
        )
        if (
            version.launch_failed
            or version.timed_out
            or version.output_exceeded
            or version.invalid_encoding
        ):
            return _capture_result(version)
        match = re.match(r"^(\d+\.\d+\.\d+)\b", version.stdout)
        if version.exit_code != 0 or not match or match.group(1) != qualification.version:
            return RunnerResult(status="invalid_output", error_code="unqualified_cli_version")
        auth = run_process(
            [*self._command, "auth", "status"],
            cwd=request.workspace,
            environment=environment,
            timeout_seconds=10,
            max_output_bytes=16384,
        )
        if auth.launch_failed or auth.timed_out or auth.output_exceeded or auth.invalid_encoding:
            # Never expose raw auth metadata (which may include account identifiers).
            return _capture_result(
                ProcessCapture(
                    exit_code=auth.exit_code,
                    duration_seconds=auth.duration_seconds,
                    timed_out=auth.timed_out,
                    output_exceeded=auth.output_exceeded,
                    invalid_encoding=auth.invalid_encoding,
                    launch_failed=auth.launch_failed,
                )
            )
        try:
            metadata = load_unique_json(auth.stdout)
            authenticated = (
                auth.exit_code == 0
                and isinstance(metadata, dict)
                and metadata.get("loggedIn") is True
                and metadata.get("authMethod") == "claude.ai"
            )
        except (ValueError, RecursionError):
            authenticated = False
        if not authenticated:
            return RunnerResult(status="auth_error", error_code="subscription_login_required")
        tools = ",".join(request.allowed_tools)
        arguments = [
            *self._command,
            "-p",
            "--output-format",
            "json",
            "--max-turns",
            str(request.max_turns),
            "--tools",
            tools,
            "--permission-mode",
            "dontAsk",
            "--permission-prompts",
            "none",
            "--disallowedTools",
            "mcp__*",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--setting-sources",
            "",
        ]
        if tools:
            arguments.extend(("--allowedTools", tools))
        return _capture_result(
            run_process(
                arguments,
                cwd=request.workspace,
                environment=environment,
                input_text=request.prompt,
                timeout_seconds=request.timeout_seconds,
            )
        )
