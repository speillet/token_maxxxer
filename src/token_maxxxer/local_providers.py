"""Local authenticated runtimes used only for the supervisor's text protocol."""

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import SecretStr

from token_maxxxer.commands import run_command
from token_maxxxer.json_io import load_unique_json
from token_maxxxer.models import UsageObservation, utc_now
from token_maxxxer.provider_errors import classify_failure
from token_maxxxer.results import GenerationResult

if TYPE_CHECKING:
    from token_maxxxer.providers import GenerationRequest

_ENVIRONMENT = {
    "HOME",
    "PATH",
    "USER",
    "LOGNAME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "CODEX_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
}


def runtime_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key in _ENVIRONMENT}


class CodexProvider:
    def generate(self, request: "GenerationRequest", credential: SecretStr) -> GenerationResult:
        started = time.monotonic()
        executable = shutil.which("codex")
        if not executable:
            return GenerationResult(status="auth_error", error_code="codex_cli_required")
        disabled = (
            "shell_tool",
            "view_image",
            "apps",
            "plugins",
            "multi_agent",
            "browser_use",
            "computer_use",
            "image_generation",
            "hooks",
            "memories",
            "skill_mcp_dependency_install",
            "unbounded_connection_retries",
        )
        command = [
            executable,
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--color",
            "never",
            f"--model={request.settings.model}",
            "-c",
            'approval_policy="never"',
            "-c",
            'web_search="disabled"',
        ]
        for feature in disabled:
            command.extend(["-c", f"features.{feature}=false"])
        command.append("-")
        with tempfile.TemporaryDirectory(prefix="token-maxxxer-codex-") as directory:
            result = run_command(
                command,
                Path(directory),
                request.settings.timeout_seconds,
                runtime_environment(),
                max_output_bytes=1_048_576,
                input_bytes=request.prompt.encode("utf-8"),
            )
        duration = time.monotonic() - started
        if result.timed_out:
            return GenerationResult(
                status="timeout", error_code="codex_timeout", duration_seconds=duration
            )
        if result.truncated:
            return GenerationResult(
                status="invalid_output",
                error_code="codex_output_too_large",
                duration_seconds=duration,
            )
        text = response_id = None
        usage = None
        completed = failed = False
        try:
            for line in result.output.decode("utf-8").splitlines():
                event = load_unique_json(line)
                if not isinstance(event, dict):
                    raise ValueError("invalid event")
                kind = event.get("type")
                if kind == "thread.started":
                    response_id = event.get("thread_id")
                elif kind in ("turn.failed", "error"):
                    failure = event.get("error", event)
                    if isinstance(failure, dict):
                        status, code = classify_failure(failure.get("code"), failure.get("message"))
                        return GenerationResult(
                            status=status, error_code=code, duration_seconds=duration
                        )
                    failed = True
                elif kind == "turn.completed":
                    completed = True
                    counts = event.get("usage")
                    if isinstance(counts, dict):
                        usage = UsageObservation(
                            observed_at=utc_now(),
                            source="codex_cli",
                            input_tokens=counts.get("input_tokens"),
                            output_tokens=counts.get("output_tokens"),
                        )
                elif kind in ("item.started", "item.updated", "item.completed"):
                    item = event.get("item")
                    if not isinstance(item, dict) or item.get("type") not in {
                        "agent_message",
                        "reasoning",
                        "plan",
                    }:
                        return GenerationResult(
                            status="invalid_output",
                            error_code="codex_unexpected_tool_event",
                            duration_seconds=duration,
                        )
                    if kind == "item.completed" and item.get("type") == "agent_message":
                        text = item.get("text")
            if (
                result.exit_code != 0
                or failed
                or not completed
                or not isinstance(text, str)
                or not text.strip()
            ):
                raise ValueError("incomplete turn")
            return GenerationResult(
                status="success",
                text=text,
                response_id=response_id,
                usage=usage,
                duration_seconds=duration,
                provider="codex",
                model=request.settings.model,
            )
        except (ValueError, UnicodeError, TypeError):
            return GenerationResult(
                status="invalid_output",
                error_code="codex_incomplete_turn",
                duration_seconds=duration,
            )


class CopilotProvider:
    def generate(self, request: "GenerationRequest", credential: SecretStr) -> GenerationResult:
        started = time.monotonic()
        payload = json.dumps(
            {
                "prompt": request.prompt,
                "model": request.settings.model,
                "timeout_seconds": request.settings.timeout_seconds,
                "credential": credential.get_secret_value(),
            }
        ).encode("utf-8")
        with tempfile.TemporaryDirectory(prefix="token-maxxxer-copilot-") as directory:
            result = run_command(
                [sys.executable, "-m", "token_maxxxer.copilot_worker"],
                Path(directory),
                request.settings.timeout_seconds,
                runtime_environment(),
                max_output_bytes=1_048_576,
                input_bytes=payload,
            )
        if result.timed_out:
            return GenerationResult(
                status="timeout",
                error_code="copilot_timeout",
                duration_seconds=time.monotonic() - started,
            )
        if not result.truncated and result.exit_code == 0:
            try:
                return GenerationResult.model_validate(
                    load_unique_json(result.output.decode("utf-8"))
                )
            except (ValueError, UnicodeError):
                pass
        return GenerationResult(
            status="invalid_output",
            error_code="copilot_worker_failed",
            duration_seconds=time.monotonic() - started,
        )
