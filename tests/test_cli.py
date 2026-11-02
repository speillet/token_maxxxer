import io
import json
import subprocess

import pytest
import yaml
from pydantic import SecretStr

from token_maxxxer.cli import main
from token_maxxxer.config import load_config
from token_maxxxer.providers import MAX_PROMPT_CHARACTERS
from token_maxxxer.results import GenerationResult
from token_maxxxer.storage import TaskStore


def test_empty_read_commands_do_not_create_runtime_files(config_path, capsys) -> None:
    for arguments in [("tasks", "list", "--json"), ("run", "--dry-run", "--json")]:
        assert main(["--config", str(config_path), *arguments]) == 0
        output = json.loads(capsys.readouterr().out)
        if isinstance(output, dict):
            assert output["task"] is None
            assert output["execution_enabled"] is False
            assert output["schedule_evaluated"] is False
        else:
            assert output == []
    assert not (config_path.parent / "var").exists()


def test_import_list_and_preview_cli(config_path, task, capsys) -> None:
    document = config_path.parent / "tasks.yaml"
    document.write_text(yaml.safe_dump({"tasks": [task.model_dump(mode="json")]}))
    assert main(["--config", str(config_path), "tasks", "import", str(document), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"inserted": 1, "unchanged": 0}
    config = load_config(config_path)
    before = config.storage.database.read_bytes()
    assert main(["--config", str(config_path), "run", "--dry-run", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["task"]["id"] == task.id
    assert output["status"] == "pending"
    assert TaskStore(config.storage.database).list_tasks()[0].status == "pending"
    assert config.storage.database.read_bytes() == before


def test_actual_execution_is_not_available(config_path) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--config", str(config_path), "run", "--once"])
    assert error.value.code == 2
    assert not (config_path.parent / "var").exists()


def test_configuration_errors_do_not_include_values(config_path, capsys) -> None:
    with config_path.open("a") as stream:
        stream.write("unknown: super-secret-value\n")
    assert main(["--config", str(config_path), "tasks", "list"]) == 2
    error = capsys.readouterr().err
    assert "unknown" in error
    assert "super-secret-value" not in error
    assert "Traceback" not in error


def test_doctor_uses_api_configuration_without_claude_or_secret_retrieval(
    config_path, monkeypatch, capsys
) -> None:
    subprocess.run(["git", "init", "-q", str(config_path.parent)], check=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fixture-private-key")
    original_run = subprocess.run

    def only_git(arguments, **kwargs):
        assert "git" in arguments[0]
        return original_run(arguments, **kwargs)

    monkeypatch.setattr(subprocess, "run", only_git)
    assert main(["--config", str(config_path), "doctor", "--json"]) == 0
    output = capsys.readouterr().out
    assert "sk-fixture-private-key" not in output
    checks = json.loads(output)["checks"]
    assert next(check for check in checks if check["name"] == "provider")["status"] == "ok"
    assert not (config_path.parent / "var").exists()


def test_doctor_missing_selected_key_is_an_error(config_path, monkeypatch, capsys) -> None:
    subprocess.run(["git", "init", "-q", str(config_path.parent)], check=True)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOKEN_MAXXXER_CLAUDE_CREDENTIAL_REF", raising=False)
    assert main(["--config", str(config_path), "doctor", "--json"]) == 1
    checks = json.loads(capsys.readouterr().out)["checks"]
    assert (
        next(check for check in checks if check["name"] == "credential_configuration")["status"]
        == "error"
    )


def test_query_uses_common_provider_interface_and_leaves_queue_untouched(
    config_path, monkeypatch, capsys
) -> None:
    prompt_path = config_path.parent / "prompt.txt"
    prompt_path.write_text("Explicit prompt.")
    captured = []

    class FakeProvider:
        def generate(self, request, credential):
            captured.append((request, credential))
            return GenerationResult(status="success", text="Test result.")

    monkeypatch.setattr("token_maxxxer.cli.create_provider", lambda _: FakeProvider())
    monkeypatch.setattr(
        "token_maxxxer.cli.resolve_credential", lambda *args: SecretStr("sk-fixture-private")
    )
    assert (
        main(["--config", str(config_path), "query", "--prompt-file", str(prompt_path), "--json"])
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "success"
    assert output["text"] == "Test result."
    assert "sk-fixture-private" not in json.dumps(output)
    assert captured[0][0].prompt == "Explicit prompt."
    assert captured[0][0].settings.name == "claude"
    assert not (config_path.parent / "var").exists()


def test_dry_run_never_creates_a_provider_or_resolves_credentials(
    config_path, monkeypatch, capsys
) -> None:
    def forbidden(*args):
        raise AssertionError("read-only command must not resolve credentials or use a provider")

    monkeypatch.setattr("token_maxxxer.cli.create_provider", forbidden)
    monkeypatch.setattr("token_maxxxer.cli.resolve_credential", forbidden)
    assert main(["--config", str(config_path), "run", "--dry-run", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["provider"]["name"] == "claude"


@pytest.mark.parametrize("stdin", [False, True])
def test_oversized_prompt_is_rejected_before_provider_or_credential_access(
    config_path, monkeypatch, capsys, stdin
) -> None:
    text = "\n" + "a" * MAX_PROMPT_CHARACTERS + " final instruction"
    prompt_path = config_path.parent / "prompt.txt"
    prompt_path.write_text(text)
    if stdin:
        monkeypatch.setattr("sys.stdin", io.StringIO(text))

    def forbidden(*args):
        raise AssertionError("no provider or credential resolution allowed")

    monkeypatch.setattr("token_maxxxer.cli.create_provider", forbidden)
    monkeypatch.setattr("token_maxxxer.cli.resolve_credential", forbidden)
    source = "-" if stdin else str(prompt_path)
    assert main(["--config", str(config_path), "query", "--prompt-file", source]) == 2
    assert "nothing was sent" in capsys.readouterr().err
