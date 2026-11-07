import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from token_maxxxer import copilot_worker
from token_maxxxer.commands import CommandResult, run_command
from token_maxxxer.config import ProviderConfig
from token_maxxxer.credentials import resolve_credential
from token_maxxxer.local_providers import CodexProvider, CopilotProvider
from token_maxxxer.providers import GenerationRequest


def request(name="codex", timeout=2):
    return GenerationRequest(
        prompt="Private prompt.\nReturn JSON.",
        settings=ProviderConfig(name=name, model="fixture", timeout_seconds=timeout),
    )


def test_codex_uses_cached_login_and_private_stdin_without_inheriting_api_keys(
    tmp_path, monkeypatch
):
    executable = tmp_path / "codex"
    executable.write_text(
        f"#!{sys.executable}\n"
        + """import json, os, sys
assert sys.stdin.read() == "Private prompt.\\nReturn JSON."
assert "Private prompt." not in " ".join(sys.argv)
names = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GH_TOKEN", "CODEX_API_KEY")
assert not any(name in os.environ for name in names)
assert "--ephemeral" in sys.argv and "--ignore-user-config" in sys.argv
assert "features.shell_tool=false" in sys.argv
assert "read-only" in sys.argv and "--model=fixture" in sys.argv
print(json.dumps({"type":"item.completed", "item":{"type":"agent_message","text":"Done"}}))
print(json.dumps({"type":"turn.completed","usage":{"input_tokens":11,"output_tokens":3}}))
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setattr("token_maxxxer.local_providers.shutil.which", lambda name: str(executable))
    for name in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GH_TOKEN", "CODEX_API_KEY"]:
        monkeypatch.setenv(name, "fixture-secret")
    assert (
        resolve_credential(
            ProviderConfig(name="codex", model="fixture"), tmp_path / ".env"
        ).get_secret_value()
        == ""
    )
    result = CodexProvider().generate(request(), SecretStr("must-not-be-forwarded"))
    assert result.status == "success" and result.text == "Done"
    assert result.usage.input_tokens == 11


@pytest.mark.parametrize(
    "events,exit_code,expected",
    [
        (
            [
                {
                    "type": "turn.failed",
                    "error": {"code": "usage_limit_reached", "message": "fixture-secret"},
                }
            ],
            1,
            "quota_exhausted",
        ),
        (
            [{"type": "item.completed", "item": {"type": "agent_message", "text": "Partial"}}],
            0,
            "invalid_output",
        ),
        (
            [
                {"type": "item.completed", "item": {"type": "command_execution"}},
                {"type": "turn.completed"},
            ],
            0,
            "invalid_output",
        ),
        ([{"type": "turn.completed"}], 1, "invalid_output"),
    ],
)
def test_codex_rejects_incomplete_and_tool_results_and_classifies_quota(
    monkeypatch, events, exit_code, expected
):
    monkeypatch.setattr("token_maxxxer.local_providers.shutil.which", lambda name: "/fixture/codex")
    data = "\n".join(json.dumps(event) for event in events).encode()
    monkeypatch.setattr(
        "token_maxxxer.local_providers.run_command",
        lambda *args, **kwargs: CommandResult(exit_code, data),
    )
    result = CodexProvider().generate(request(), SecretStr(""))
    assert result.status == expected
    assert "fixture-secret" not in result.model_dump_json()


def test_runtime_input_handles_large_prompts_and_timeout(tmp_path):
    data = b"private-input" * 100_000
    result = run_command(
        [sys.executable, "-c", "import sys; print(len(sys.stdin.buffer.read()))"],
        tmp_path,
        2,
        os.environ,
        input_bytes=data,
    )
    assert result.exit_code == 0 and int(result.output) == len(data)
    timeout = run_command(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        tmp_path,
        0.1,
        os.environ,
        input_bytes=data,
    )
    assert timeout.timed_out


@pytest.mark.parametrize("failure", [None, "quota", "timeout", "startup_quota"])
def test_copilot_sdk_disables_tools_classifies_failures_and_stops(monkeypatch, failure):
    observed = {}

    class Client:
        def __init__(self, **kwargs):
            observed["client"] = kwargs

        async def start(self):
            pass

        async def create_session(self, **kwargs):
            observed["session"] = kwargs
            if failure == "startup_quota":
                raise RuntimeError("quota exceeded fixture-secret")
            return self

        async def send_and_wait(self, prompt, **kwargs):
            assert prompt == "Private prompt"
            if failure == "timeout":
                await asyncio.sleep(10)
            if failure == "quota":
                observed["session"]["on_event"](
                    SimpleNamespace(
                        type="session.error",
                        data=SimpleNamespace(
                            error_type="quota_exceeded", message="fixture-secret", status_code=429
                        ),
                        agent_id=None,
                    )
                )
                raise RuntimeError("fixture-secret")
            return SimpleNamespace(
                data=SimpleNamespace(content="Done", message_id="fixture-message")
            )

        async def force_stop(self):
            observed["stopped"] = True

    monkeypatch.setattr(
        copilot_worker.importlib,
        "import_module",
        lambda name: SimpleNamespace(
            CopilotClient=Client,
            PermissionDecisionUserNotAvailable=lambda: SimpleNamespace(kind="user-not-available"),
        ),
    )
    result = asyncio.run(
        copilot_worker.generate(
            {
                "credential": "",
                "prompt": "Private prompt",
                "model": "fixture",
                "timeout_seconds": 0.02 if failure == "timeout" else 1,
            }
        )
    )
    assert (
        result.status
        == {
            "quota": "quota_exhausted",
            "startup_quota": "quota_exhausted",
            "timeout": "timeout",
            None: "success",
        }[failure]
    )
    assert observed["stopped"]
    assert observed["client"]["use_logged_in_user"] is True
    assert observed["session"]["available_tools"] == []
    assert observed["session"]["enable_session_store"] is False
    assert observed["session"]["enable_config_discovery"] is False
    denial = observed["session"]["on_permission_request"](object(), session_id="fixture")
    assert denial.kind == "user-not-available"
    assert "fixture-secret" not in result.model_dump_json()


def test_copilot_parent_passes_credentials_only_through_private_input(monkeypatch):
    def execute(command, root, timeout, environment, **kwargs):
        assert command == [sys.executable, "-m", "token_maxxxer.copilot_worker"]
        assert "fixture-secret" not in " ".join(command)
        assert "fixture-secret" not in environment.values()
        assert json.loads(kwargs["input_bytes"])["credential"] == "fixture-secret"
        return CommandResult(0, b'{"status":"success","text":"Done"}')

    monkeypatch.setattr("token_maxxxer.local_providers.run_command", execute)
    assert (
        CopilotProvider().generate(request("copilot"), SecretStr("fixture-secret")).status
        == "success"
    )
