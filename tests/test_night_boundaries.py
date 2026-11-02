import json
import os
import shlex
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import SecretStr

from token_maxxxer.cli import main
from token_maxxxer.config import ProviderConfig
from token_maxxxer.file_tools import FileTools
from token_maxxxer.local_state import write_private_text
from token_maxxxer.night import NightPlan, NightSession, public_session_json, run_night
from token_maxxxer.results import GenerationResult
from token_maxxxer.skills import discover_skills, select_skill


def commit_fixture(repository) -> None:
    subprocess.run(["git", "-C", str(repository), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "-qm",
            "Add fixture configuration",
        ],
        check=True,
    )


@pytest.mark.parametrize("name", [".npmrc", ".netrc", ".pypirc", ".git-credentials", ".yarnrc.yml"])
def test_conventional_credential_files_are_excluded(repository, name) -> None:
    (repository / name).write_text("_authToken=npm_fictional_fixture_only\n")
    subprocess.run(["git", "-C", str(repository), "add", "--", name], check=True)
    tools = FileTools(repository, editable=False)
    assert name not in tools.catalog
    with pytest.raises(ValueError):
        tools.read_file(name)


def test_repository_skill_resources_follow_tracking_and_ignore_rules(repository) -> None:
    directory = repository / ".agents/skills/demo"
    directory.mkdir(parents=True)
    (directory / "guide.md").write_text("Read this tracked guide.")
    (directory / "private.txt").write_text("Private ignored resource.")
    (repository / ".gitignore").write_text("private.txt\n")
    subprocess.run(
        ["git", "-C", str(repository), "add", ".agents/skills/demo/guide.md"], check=True
    )
    tools = FileTools(repository, editable=False, skill_directory=directory)
    assert tools.read_skill_file("guide.md") == "Read this tracked guide."
    with pytest.raises(ValueError):
        tools.read_skill_file("private.txt")


def test_symlinked_skill_ancestors_are_not_discovered(repository, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    outside = tmp_path / "outside/skills/escaped"
    outside.mkdir(parents=True)
    (outside / "SKILL.md").write_text("---\nname: escaped\n---\nExternal instructions.")
    (repository / ".agents").symlink_to(tmp_path / "outside", target_is_directory=True)
    assert not any(skill.id == "repo:escaped" for skill in discover_skills(repository))


@pytest.mark.parametrize(
    "arguments",
    [
        ("check", "sk-fixture-private-value"),
        ("check", "--password", "fictional-private"),
        ("check", "--token=fictional-private"),
        ("check", "--refresh-token", "fictional-private"),
        ("check", "--client-secret", "fictional-private"),
        ("check", "--auth-token", "fictional-private"),
        ("check", "--refreshToken", "fictional-private"),
        ("check", "PROVIDER_API_KEY=fictional-private"),
    ],
)
def test_verification_credentials_are_rejected_before_persistence(repository, arguments) -> None:
    with pytest.raises(ValueError) as error:
        NightPlan(
            repository=repository,
            skill="builtin:improve-code",
            provider=ProviderConfig(model="fixture"),
            verification_commands=(arguments,),
        )
    assert "fictional-private" not in str(error.value)
    assert "sk-fixture-private-value" not in str(error.value)


@pytest.mark.parametrize(
    "arguments",
    [
        ("pytest", "-k", "token"),
        ("npm", "run", "lint:secret"),
        ("make", "key"),
    ],
)
def test_positional_credential_words_are_allowed(repository, arguments) -> None:
    plan = NightPlan(
        repository=repository,
        skill="builtin:improve-code",
        provider=ProviderConfig(model="fixture"),
        verification_commands=(arguments,),
    )
    assert plan.verification_commands == (arguments,)


def test_public_session_serialization_redacts_defensively(repository) -> None:
    plan = NightPlan(
        repository=repository,
        skill="builtin:improve-code",
        provider=ProviderConfig(model="fixture"),
    )
    session = NightSession(
        id="fixture",
        plan=plan,
        started_at="fixture",
        base_commit="fixture",
        summaries=["A manually modified record with sk-fixture-private-value"],
    )
    assert "sk-fixture-private-value" not in public_session_json(session)


def test_repository_skill_resources_are_read_from_isolated_worktree(repository, tmp_path) -> None:
    directory = repository / ".agents/skills/demo"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("---\nname: demo\n---\nRead guide.md.")
    (directory / "guide.md").write_text("Original guide.\n")
    commit_fixture(repository)
    skill = select_skill(discover_skills(repository), "repo:demo", mode="edit")
    plan = NightPlan(
        repository=repository, skill=skill.id, provider=ProviderConfig(model="fixture")
    )
    actions = iter(
        [
            {"type": "read_skill_file", "path": "guide.md"},
            {
                "type": "write_file",
                "path": ".agents/skills/demo/guide.md",
                "content": "Updated guide.\n",
            },
            {"type": "read_skill_file", "path": "guide.md"},
            {"type": "finish", "summary": "Updated guide in the worktree."},
        ]
    )
    requests = []

    class FakeProvider:
        def generate(self, request, credential):
            requests.append(request)
            return GenerationResult(status="success", text=json.dumps({"action": next(actions)}))

    session = run_night(plan, skill, tmp_path / "state", FakeProvider(), SecretStr("fixture"))
    assert session.reason == "skill_completed"
    assert (directory / "guide.md").read_text() == "Original guide.\n"
    assert "Updated guide.\\n" in requests[3].prompt


def test_failed_report_replacement_preserves_previous_private_record(tmp_path, monkeypatch) -> None:
    path = tmp_path / "report.md"
    write_private_text(path, "Complete previous report.\n")

    def fail_replace(*args):
        raise OSError("Simulated replacement failure.")

    monkeypatch.setattr("token_maxxxer.local_state.os.replace", fail_replace)
    with pytest.raises(OSError):
        write_private_text(path, "Unfinished new report.\n")
    assert path.read_text() == "Complete previous report.\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("preview", [True, False])
def test_preview_and_cancellation_never_execute_repository_clean_filters(
    config_path, repository, tmp_path, monkeypatch, capsys, preview
) -> None:
    marker = tmp_path / "filter-executed"
    code = (
        "import sys; from pathlib import Path; "
        f"Path({str(marker)!r}).write_text('executed'); "
        "sys.stdout.buffer.write(sys.stdin.buffer.read())"
    )
    (repository / ".gitattributes").write_text("main.py filter=fixture\n")
    commit_fixture(repository)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "config",
            "filter.fixture.clean",
            shlex.join((sys.executable, "-c", code)),
        ],
        check=True,
    )
    file_stat = (repository / "main.py").stat()
    os.utime(repository / "main.py", (file_stat.st_atime, file_stat.st_mtime + 2))
    marker.unlink(missing_ok=True)

    def forbid_api(*args):
        raise AssertionError("preview must not access credentials or an API client")

    monkeypatch.setattr("token_maxxxer.night_cli.resolve_credential", forbid_api)
    monkeypatch.setattr("token_maxxxer.night_cli.create_provider", forbid_api)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "no")
    flags = ["--dry-run", "--json"] if preview else []
    assert (
        main(
            [
                "--config",
                str(config_path),
                "--state-dir",
                str(tmp_path / "state"),
                "night",
                str(repository),
                *flags,
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert not marker.exists()
    # Prove this fixture would execute its filter if a preview called Git status.
    subprocess.run(
        ["git", "-C", str(repository), "status", "--porcelain"],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    assert marker.exists()
