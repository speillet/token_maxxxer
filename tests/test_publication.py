import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from token_maxxxer.config import ProviderConfig
from token_maxxxer.night import NightPlan, run_night
from token_maxxxer.publication import (
    PublicationConfig,
    PublicationError,
    PublicationRecord,
    Publisher,
    github_repository,
    publication_config,
)
from token_maxxxer.results import GenerationResult
from token_maxxxer.skills import discover_skills, select_skill

BRANCH = "token_maxxxer/night-20261104T220000Z-aabbccdd"


def git(root, *arguments):
    return subprocess.check_output(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "-c",
            "commit.gpgsign=false",
            *arguments,
        ],
        text=True,
    ).strip()


@pytest.fixture
def github(repository, tmp_path, monkeypatch):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    git(repository, "branch", "-M", "main")
    git(repository, "push", "-q", str(bare), "HEAD:refs/heads/main")
    monkeypatch.setattr("token_maxxxer.publication.shutil.which", lambda _: "gh-fixture")
    backend = SimpleNamespace(
        remote=bare,
        pr=None,
        creates=0,
        edits=0,
        write_access=True,
        push_error=None,
        create_error=None,
    )

    class LocalPublisher(Publisher):
        def _git(self, *arguments, **kwargs):
            local = tuple(str(bare) if value == self.config.url else value for value in arguments)
            if arguments[0] == "push" and backend.push_error == "before":
                raise PublicationError("publication_command_failed")
            output = super()._git(
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.test",
                "-c",
                "commit.gpgsign=false",
                *local,
                **kwargs,
            )
            if arguments[0] == "push" and backend.push_error == "after":
                raise PublicationError("publication_command_failed")
            return output

        def _command(self, arguments, **kwargs):
            if arguments[0] != self.gh:
                return super()._command(arguments, **kwargs)
            if arguments[1:3] == ["repo", "view"]:
                return json.dumps(
                    {
                        "nameWithOwner": "example/project",
                        "viewerPermission": "WRITE" if backend.write_access else "READ",
                    }
                ).encode()
            raise AssertionError("every GitHub operation must be simulated")

        def _gh(self, *arguments):
            assert arguments[0] == "pr"
            action = arguments[1]
            if action == "list":
                if backend.pr is None:
                    return b"[]"
                pr = dict(backend.pr)
                pr["headRefOid"] = git(bare, "rev-parse", f"refs/heads/{pr['headRefName']}")
                return json.dumps([pr]).encode()
            if action == "create":
                backend.creates += 1
                if backend.create_error == "before":
                    raise PublicationError("publication_command_failed")
                branch = arguments[arguments.index("--head") + 1]
                backend.pr = {
                    "number": 1,
                    "url": "https://github.com/example/project/pull/1",
                    "state": "OPEN",
                    "isDraft": True,
                    "headRefName": branch,
                    "baseRefName": "main",
                    "isCrossRepository": False,
                }
            elif action == "edit":
                backend.edits += 1
            else:
                raise AssertionError(f"unapproved GitHub mutation: {action}")
            backend.pr["body"] = Path(arguments[arguments.index("--body-file") + 1]).read_text()
            if backend.create_error == "after" and action == "create":
                raise PublicationError("publication_command_failed")
            return b"https://github.com/example/project/pull/1\n"

    backend.publisher = LocalPublisher
    backend.config = PublicationConfig(repository="example/project", base_branch="main")
    return backend


@pytest.mark.parametrize(
    "remote",
    [
        "https://github.com/example/project.git",
        "git@github.com:example/project.git",
        "ssh://git@github.com/example/project",
    ],
)
def test_github_origin_parsing(remote):
    assert github_repository(remote) == "example/project"


@pytest.mark.parametrize(
    "remote",
    [
        "https://attacker.invalid/example/project",
        "file:///tmp/repo",
        "https://secret@github.com/example/project",
        "https://github.com:sk-fixture-secret/example/project",
        "https://github.com/example/project?token=secret",
        "git@attacker.invalid:example/project",
    ],
)
def test_other_or_credential_bearing_origins_are_rejected(remote):
    with pytest.raises(PublicationError) as error:
        github_repository(remote)
    assert "secret" not in str(error.value)


def test_local_destination_discovery_requires_no_network(repository):
    git(repository, "remote", "add", "origin", "git@github.com:example/project.git")
    git(repository, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    assert publication_config(repository, None).base_branch == "main"


def test_publish_two_verified_batches_updates_one_draft(repository, github, tmp_path):
    git(repository, "switch", "-c", BRANCH)
    publisher = github.publisher(github.config, repository)
    publisher.preflight()
    record = PublicationRecord()
    events = []
    for index in range(2):
        (repository / "main.py").write_text(f"print({index})\n")
        publisher.publish(
            BRANCH,
            {"main.py"},
            "improve-code",
            [f"Fix issue {index}."],
            record,
            tmp_path,
            lambda: events.append(record.phase),
        )
    assert len(record.commits) == 2
    assert record.phase == "published"
    assert record.pr_url == "https://github.com/example/project/pull/1"
    assert github.creates == 1 and github.edits == 1
    assert git(github.remote, "rev-parse", f"refs/heads/{BRANCH}") == record.commits[-1]
    assert "committing" in events and "pushing" in events and "opening_pr" in events


@pytest.mark.parametrize("failure", ["before", "after"])
def test_push_failure_is_reconciled_read_only(repository, github, tmp_path, failure):
    git(repository, "switch", "-c", BRANCH)
    (repository / "main.py").write_text("print('changed')\n")
    github.push_error = failure
    record = PublicationRecord()
    publisher = github.publisher(github.config, repository)
    if failure == "before":
        with pytest.raises(PublicationError, match="uncertain"):
            publisher.publish(
                BRANCH, {"main.py"}, "improve-code", [], record, tmp_path, lambda: None
            )
        assert record.phase == "uncertain"
        assert github.creates == 0
    else:
        publisher.publish(BRANCH, {"main.py"}, "improve-code", [], record, tmp_path, lambda: None)
        assert record.phase == "published"
        assert github.creates == 1


def test_ambiguous_pr_creation_does_not_open_a_duplicate(repository, github, tmp_path):
    git(repository, "switch", "-c", BRANCH)
    (repository / "main.py").write_text("print('changed')\n")
    github.create_error = "after"
    record = PublicationRecord()
    github.publisher(github.config, repository).publish(
        BRANCH, {"main.py"}, "improve-code", [], record, tmp_path, lambda: None
    )
    assert record.phase == "published" and github.creates == 1


@pytest.mark.parametrize("unsafe", ["secret", "unowned", "staged", "symlink"])
def test_unsafe_work_is_not_committed_or_pushed(repository, github, tmp_path, unsafe):
    git(repository, "switch", "-c", BRANCH)
    original = git(repository, "rev-parse", "HEAD")
    path = repository / "main.py"
    path.write_text("print('candidate')\n")
    if unsafe == "secret":
        path.write_text('api_key = "sk-fixture-private-value"\n')
    elif unsafe == "unowned":
        (repository / "unowned.txt").write_text("Must not publish.")
    elif unsafe == "staged":
        git(repository, "add", "main.py")
    else:
        path.unlink()
        path.symlink_to(tmp_path / "outside")
    with pytest.raises(PublicationError):
        github.publisher(github.config, repository).publish(
            BRANCH, {"main.py"}, "improve-code", [], PublicationRecord(), tmp_path, lambda: None
        )
    assert git(repository, "rev-parse", "HEAD") == original
    assert github.creates == 0


def test_existing_remote_branch_is_not_overwritten(repository, github, tmp_path):
    git(repository, "switch", "-c", BRANCH)
    git(repository, "push", "-q", str(github.remote), f"HEAD:refs/heads/{BRANCH}")
    (repository / "main.py").write_text("print('candidate')\n")
    with pytest.raises(PublicationError, match="remote_branch_changed"):
        github.publisher(github.config, repository).publish(
            BRANCH, {"main.py"}, "improve-code", [], PublicationRecord(), tmp_path, lambda: None
        )


@pytest.mark.parametrize("state,draft", [("CLOSED", True), ("MERGED", True), ("OPEN", False)])
def test_human_review_or_closure_stops_publication(repository, github, tmp_path, state, draft):
    git(repository, "switch", "-c", BRANCH)
    record = PublicationRecord()
    publisher = github.publisher(github.config, repository)
    (repository / "main.py").write_text("print('first')\n")
    publisher.publish(BRANCH, {"main.py"}, "improve-code", [], record, tmp_path, lambda: None)
    github.pr.update(state=state, isDraft=draft)
    (repository / "main.py").write_text("print('second')\n")
    with pytest.raises(PublicationError):
        publisher.publish(BRANCH, {"main.py"}, "improve-code", [], record, tmp_path, lambda: None)
    assert len(record.commits) == 1


def test_headless_session_publishes_from_remote_without_user_local_commits(
    repository, github, tmp_path, monkeypatch
):
    (repository / "local-only.txt").write_text("Unpublished user content.\n")
    git(repository, "add", "local-only.txt")
    git(repository, "commit", "-qm", "Unpublished user commit")
    original_head = git(repository, "rev-parse", "HEAD")
    (repository / "main.py").write_text("Uncommitted user edits.\n")
    monkeypatch.setattr("token_maxxxer.night.Publisher", github.publisher)
    actions = iter(
        [
            {"type": "read_file", "path": "main.py"},
            {"type": "write_file", "path": "main.py", "content": "print('verified improvement')\n"},
            {"type": "finish", "summary": "Improve the example."},
        ]
    )

    class Provider:
        def generate(self, request, credential):
            return GenerationResult(status="success", text=json.dumps({"action": next(actions)}))

    plan = NightPlan(
        repository=repository,
        skill="builtin:improve-code",
        provider=ProviderConfig(model="fixture"),
        publication=github.config,
        verification_commands=((sys.executable, "-B", "-c", "import main"),),
    )
    skill = select_skill(discover_skills(repository), plan.skill, mode="edit")
    session = run_night(plan, skill, tmp_path / "state", Provider(), SecretStr("fixture"))
    assert session.state == "completed", session.model_dump_json()
    assert session.publication.phase == "published"
    assert not (session.worktree / "local-only.txt").exists()
    assert (repository / "main.py").read_text() == "Uncommitted user edits.\n"
    assert git(repository, "rev-parse", "HEAD") == original_head


def test_failed_checks_leave_work_local(repository, github, tmp_path, monkeypatch):
    monkeypatch.setattr("token_maxxxer.night.Publisher", github.publisher)
    actions = iter(
        [
            {"type": "write_file", "path": "new.py", "content": "# Candidate.\n"},
            {"type": "finish", "summary": "Candidate needs correction."},
        ]
    )

    class Provider:
        def generate(self, request, credential):
            return GenerationResult(status="success", text=json.dumps({"action": next(actions)}))

    plan = NightPlan(
        repository=repository,
        skill="builtin:improve-code",
        provider=ProviderConfig(model="fixture"),
        publication=github.config,
        verification_commands=((sys.executable, "-c", "raise SystemExit(1)"),),
    )
    skill = select_skill(discover_skills(repository), plan.skill, mode="edit")
    session = run_night(plan, skill, tmp_path / "state", Provider(), SecretStr("fixture"))
    assert session.reason == "verification_failed"
    assert github.creates == 0
    assert (session.worktree / "new.py").exists()
