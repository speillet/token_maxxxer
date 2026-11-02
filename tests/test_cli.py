import json
import subprocess
import sys

import pytest
import yaml

from nightshift.cli import main
from nightshift.config import load_config
from nightshift.doctor import API_CONFIGURATION_VARIABLES, checks_as_dicts, diagnose
from nightshift.storage import TaskStore


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


def test_doctor_missing_claude_and_api_conflict(config_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("nightshift.doctor.shutil.which", lambda _: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "super-secret-value")
    assert main(["--config", str(config_path), "doctor", "--json"]) == 1
    output = capsys.readouterr().out
    assert "ANTHROPIC_API_KEY" in output
    assert "super-secret-value" not in output
    assert not (config_path.parent / "var").exists()


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"loggedIn": True, "authMethod": "claude.ai"}, "ok"),
        ({"loggedIn": True, "authMethod": "api_key"}, "error"),
        ({"loggedIn": False, "authMethod": "claude.ai"}, "error"),
        ([], "error"),
        ("malformed", "error"),
    ],
)
def test_doctor_uses_only_metadata_and_never_runs_inference(
    config_path,
    monkeypatch,
    payload,
    expected,
) -> None:
    for variable in API_CONFIGURATION_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    subprocess.run(["git", "init", "-q", str(config_path.parent)], check=True)
    binary = config_path.parent / "claude"
    if isinstance(payload, dict):
        payload = {**payload, "email": "private@example.com", "token": "super-secret-value"}
    raw = payload if payload == "malformed" else json.dumps(payload)
    binary.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "if sys.argv[1:] == ['--version']:\n    print('2.1.999 (Claude Code)')\n"
        f"elif sys.argv[1:] == ['auth', 'status']:\n    print({raw!r})\n"
        "else:\n    raise SystemExit(99)\n"
    )
    binary.chmod(0o700)
    original_which = __import__("shutil").which
    monkeypatch.setattr(
        "nightshift.doctor.shutil.which",
        lambda name: str(binary) if name == "claude" else original_which(name),
    )
    checks = diagnose(load_config(config_path))
    assert (
        next(check for check in checks if check.name == "claude_authentication").status == expected
    )
    serialized = json.dumps(checks_as_dicts(checks))
    assert "super-secret-value" not in serialized
    assert "private@example.com" not in serialized
    assert not (config_path.parent / "var").exists()
