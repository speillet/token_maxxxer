import io
import json
import sys

import pytest
from pydantic import SecretStr

from token_maxxxer.cli import main
from token_maxxxer.repositories import load_history
from token_maxxxer.results import GenerationResult


def forbid_api(*args, **kwargs):
    raise AssertionError("this command must not resolve credentials or create an API client")


def test_repository_and_skill_listing_need_no_configuration_or_api(
    repository, tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    state = tmp_path / "state"
    monkeypatch.setattr("token_maxxxer.night_cli.resolve_credential", forbid_api)
    monkeypatch.setattr("token_maxxxer.night_cli.create_provider", forbid_api)
    assert main(["--state-dir", str(state), "repos", "--root", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [str(repository)]
    assert main(["--state-dir", str(state), "skills", "--repo", str(repository), "--json"]) == 0
    skills = json.loads(capsys.readouterr().out)
    assert any(skill["id"] == "builtin:improve-code" for skill in skills)
    assert not state.exists()


def test_night_preview_creates_no_state_worktree_or_credential_access(
    config_path, repository, tmp_path, monkeypatch, capsys
) -> None:
    state = tmp_path / "state"
    monkeypatch.setattr("token_maxxxer.night_cli.resolve_credential", forbid_api)
    monkeypatch.setattr("token_maxxxer.night_cli.create_provider", forbid_api)
    before = (repository / ".git").stat().st_mtime_ns
    assert (
        main(
            [
                "--config",
                str(config_path),
                "--state-dir",
                str(state),
                "night",
                repository.as_uri(),
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["plan"]["repository"] == str(repository)
    assert output["plan"]["skill"] == "builtin:improve-code"
    assert output["plan"]["provider"]["model"] == "fixture-model"
    assert not state.exists()
    assert (repository / ".git").stat().st_mtime_ns == before


def test_explicit_flags_work_without_a_yaml_configuration(
    repository, tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    assert (
        main(
            [
                "night",
                str(repository),
                "--provider",
                "openai",
                "--model",
                "fixture-openai",
                "--dry-run",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["plan"]["provider"]["name"] == "openai"


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--hours", "nan"],
        ["--max-calls", "0"],
        ["--mode", "review", "--verify", "python -m pytest"],
        ["--verify", ""],
    ],
)
def test_invalid_or_unconfirmed_invocation_does_not_start(
    config_path, repository, tmp_path, monkeypatch, capsys, flags
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setattr("token_maxxxer.night_cli.resolve_credential", forbid_api)
    monkeypatch.setattr("token_maxxxer.night_cli.create_provider", forbid_api)
    state = tmp_path / "state"
    assert (
        main(
            [
                "--config",
                str(config_path),
                "--state-dir",
                str(state),
                "night",
                str(repository),
                *flags,
            ]
        )
        == 2
    )
    assert not state.exists()
    assert "Error:" in capsys.readouterr().err


def test_no_arguments_explains_noninteractive_usage(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    assert main([]) == 2
    assert "terminal" in capsys.readouterr().err


def test_interactive_wizard_selects_repository_skill_and_remembers_profile(
    repository, tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    answers = iter([str(repository), "", "", "fixture-model", "1", "2", "", "local", "yes"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    class FakeProvider:
        def generate(self, request, credential):
            return GenerationResult(
                status="success",
                text=json.dumps(
                    {"action": {"type": "finish", "summary": "No useful changes remain."}}
                ),
            )

    monkeypatch.setattr("token_maxxxer.night_cli.create_provider", lambda _: FakeProvider())
    monkeypatch.setattr(
        "token_maxxxer.night_cli.resolve_credential", lambda *args: SecretStr("sk-fixture-private")
    )
    state = tmp_path / "state"
    assert main(["--state-dir", str(state)]) == 0
    output = capsys.readouterr().out
    assert "Available skills" in output
    assert "skill_completed" in output
    history = load_history(state)
    assert history.repositories[0].path == repository
    assert history.repositories[0].skill == "builtin:improve-code"
    assert json.loads((state / "profile.json").read_text())["provider"]["model"] == "fixture-model"
    assert "sk-fixture-private" not in (state / "profile.json").read_text()
    assert main(["--state-dir", str(state), "sessions", "--json"]) == 0
    sessions = json.loads(capsys.readouterr().out)
    assert len(sessions) == 1
    assert main(["--state-dir", str(state), "sessions", sessions[0]["id"]]) == 0
    assert "No useful changes remain" in capsys.readouterr().out


def test_interactive_cancellation_preserves_state_absence(
    config_path, repository, tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "no")
    monkeypatch.setattr("token_maxxxer.night_cli.resolve_credential", forbid_api)
    state = tmp_path / "state"
    assert (
        main(["--config", str(config_path), "--state-dir", str(state), "night", str(repository)])
        == 0
    )
    assert not state.exists()
    assert "cancelled" in capsys.readouterr().out
