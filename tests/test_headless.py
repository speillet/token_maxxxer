import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from token_maxxxer.headless import HeadlessJob, load_job, run_headless, scheduled_date
from token_maxxxer.headless_cron import cron_block, manage_cron, replace_block
from token_maxxxer.local_state import read_record
from token_maxxxer.repositories import git


@pytest.fixture
def job(repository, tmp_path):
    skill = repository / ".agents/skills/review-cards/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: review-cards\n---\nDeepen existing answers. Preserve IDs.\n")
    git(repository, "config", "user.name", "Fixture")
    git(repository, "config", "user.email", "fixture@example.test")
    git(repository, "add", "--", str(skill))
    git(repository, "commit", "-m", "Add review skill")
    binary = tmp_path / "codex-fixture"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import sys, re\nfrom pathlib import Path\n"
        "assert '--ephemeral' in sys.argv\n"
        "assert '--ignore-user-config' not in sys.argv\n"
        "assert sys.argv[sys.argv.index('--sandbox')+1] == 'workspace-write'\n"
        "assert 'approval_policy=\"never\"' in sys.argv\n"
        "prompt=sys.stdin.read()\n"
        "assert '$review-cards' in prompt\n"
        "subject=re.search(r'subject: (.*?), including', prompt)[1]\n"
        "p=Path(subject)\np.write_text(p.read_text()+'# Reviewed.\\n')\n"
        "print('A source excerpt that must not appear in status logs.')\n"
    )
    binary.chmod(0o700)
    return HeadlessJob(
        name="cards",
        repository=repository,
        skill_file=skill,
        state_directory=tmp_path / "private-state",
        codex_binary=binary,
        model="fixture-model",
        subjects=("main.py", "readme.md"),
        write_paths=("main.py", "readme.md", "docs/*"),
        verification_commands=(
            (sys.executable, "-c", "import ast; ast.parse(open('main.py').read())"),
        ),
    )


def test_real_graph_commits_verified_edits_rotates_subjects_and_preserves_source(job):
    original_head = git(job.repository, "rev-parse", "HEAD")
    original_file = (job.repository / "main.py").read_bytes()
    # Dirty user work is preserved: only the committed source is used by the review branch.
    (job.repository / "readme.md").write_text("User work in progress.\n")
    first = run_headless(job, now=datetime(2026, 11, 20, 21, tzinfo=UTC))
    assert first["status"] == "completed", first
    assert first["reason"] == "needs_review"
    assert first["subject"] == "main.py"
    assert git(job.repository, "rev-parse", "HEAD") == original_head
    assert (job.repository / "main.py").read_bytes() == original_file
    assert (job.repository / "readme.md").read_text() == "User work in progress.\n"
    root = Path(first["worktree"])
    assert (root / "main.py").read_text().endswith("# Reviewed.\n")
    assert not git(root, "status", "--porcelain")
    assert read_record(job.state_directory / "progress.json")["next_subject"] == 1
    log = (job.state_directory / "runs/2026-11-20/status.json").read_text()
    assert "source excerpt" not in log
    second = run_headless(job, now=datetime(2026, 11, 21, 21, tzinfo=UTC))
    assert second["status"] == "completed", second
    assert second["subject"] == "readme.md"
    assert (root / "main.py").read_text().endswith("# Reviewed.\n")
    assert (root / "readme.md").read_text().endswith("# Reviewed.\n")
    assert git(root, "rev-list", "--count", f"{original_head.strip()}..HEAD").strip() == "2"


def test_daily_attempt_is_never_replayed_even_after_failure(job):
    job.codex_binary.write_text(f"#!{sys.executable}\nraise SystemExit(1)\n")
    now = datetime(2026, 11, 20, 21, tzinfo=UTC)
    assert run_headless(job, now=now)["reason"] == "agent_failed"
    assert run_headless(job, now=now)["reason"] == "already_attempted"


def test_running_attempt_is_skipped_without_reacquiring_repository_lock(job):
    from token_maxxxer.night import _repository_lock

    now = datetime(2026, 11, 20, 21, tzinfo=UTC)
    attempt = job.state_directory / "runs/2026-11-20/attempted"
    attempt.parent.mkdir(parents=True)
    attempt.touch()
    with _repository_lock(job.repository):
        assert run_headless(job, scheduled=True, now=now)["reason"] == "already_attempted"


def test_baseline_failure_prevents_agent_execution(job):
    bad = job.model_copy(
        update={"verification_commands": ((sys.executable, "-c", "raise SystemExit(1)"),)}
    )
    result = run_headless(bad)
    assert result["reason"] == "verification_failed"
    assert not (Path(result["worktree"]) / "main.py").read_text().endswith("# Reviewed.\n")
    assert not job.state_directory.joinpath("progress.json").exists()


@pytest.mark.parametrize(
    "operation,reason",
    [
        ("Path('AGENTS.md').write_text('Weaken the rules.')", "agent_changed_unapproved_path"),
        ("Path('main.py').unlink()", "agent_removed_files"),
        ("Path('main.py').write_text('invalid python !')", "verification_failed"),
    ],
)
def test_failed_validation_preserves_uncommitted_work_without_advancing(job, operation, reason):
    job.codex_binary.write_text(f"#!{sys.executable}\nfrom pathlib import Path\n{operation}\n")
    result = run_headless(job)
    assert result["status"] == "failed", result
    assert result["reason"] == reason
    root = Path(result["worktree"])
    assert git(root, "rev-parse", "HEAD").strip() == result["base_commit"]
    assert git(root, "status", "--porcelain")
    assert not job.state_directory.joinpath("progress.json").exists()
    following = run_headless(job, now=datetime(2030, 1, 1, tzinfo=UTC))
    assert following["reason"] == "review_worktree_needs_attention"


def test_inventory_snapshot_is_supplied_to_identity_checks(job):
    inventory = (sys.executable, "-c", 'print(\'{"ids":["CARD-001"]}\')')
    check = (
        sys.executable,
        "-c",
        "import json,sys; assert json.load(open(sys.argv[1]))['ids']==['CARD-001']",
        "{inventory_before}",
    )
    configured = job.model_copy(
        update={
            "inventory_command": inventory,
            "verification_commands": (*job.verification_commands, check),
        }
    )
    result = run_headless(configured)
    assert result["status"] == "completed", result
    assert len(result["checks"]) == 6


def test_deadline_terminates_a_blocked_native_agent(job, tmp_path):
    pid_file = tmp_path / "agent.pid"
    job.codex_binary.write_text(
        f"#!{sys.executable}\nimport os,time\nfrom pathlib import Path\n"
        f"Path({str(pid_file)!r}).write_text(str(os.getpid()))\ntime.sleep(30)\n"
    )
    short = job.model_copy(update={"timeout_seconds": 2})
    started = time.monotonic()
    result = run_headless(short)
    assert time.monotonic() - started < 6
    assert result["status"] == "failed"
    assert result["reason"] in ("headless_deadline_reached", "agent_timeout")
    assert pid_file.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def test_preview_and_outside_window_have_no_side_effects(job):
    assert run_headless(job, dry_run=True)["status"] == "preview"
    assert (
        run_headless(job, scheduled=True, now=datetime(2026, 11, 20, 12, tzinfo=UTC))["reason"]
        == "outside_start_window"
    )
    assert not job.state_directory.exists()
    assert len(git(job.repository, "worktree", "list").splitlines()) == 1


@pytest.mark.parametrize(
    "stamp,expected",
    [
        ("2026-11-20T20:59:00+00:00", None),
        ("2026-11-20T21:00:00+00:00", "2026-11-20"),
        ("2026-11-20T21:59:59+00:00", "2026-11-20"),
        ("2026-11-20T22:00:00+00:00", None),
        ("2026-07-20T20:00:00+00:00", "2026-07-20"),
    ],
)
def test_schedule_uses_paris_time_and_half_open_window(job, stamp, expected):
    assert scheduled_date(job, datetime.fromisoformat(stamp)) == expected


def test_schedule_handles_midnight_and_dst_fall_back_without_duplicate_dates(job):
    late = job.model_copy(update={"daily_at": "23:30", "latest_start_minutes": 120})
    assert scheduled_date(late, datetime(2026, 11, 21, 0, tzinfo=UTC)) == "2026-11-20"
    repeated = job.model_copy(update={"daily_at": "02:00", "latest_start_minutes": 120})
    assert scheduled_date(repeated, datetime(2026, 10, 25, 0, 30, tzinfo=UTC)) == "2026-10-25"
    assert scheduled_date(repeated, datetime(2026, 10, 25, 1, 30, tzinfo=UTC)) == "2026-10-25"


def test_job_paths_resolve_from_config_and_unknown_fields_are_rejected(job, tmp_path):
    document = job.model_dump(mode="json")
    document["state_directory"] = "private-state"
    path = tmp_path / "job.json"
    path.write_text(json.dumps(document))
    assert load_job(path).state_directory == tmp_path / "private-state"
    document["surprise"] = True
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        load_job(path)


def test_sigterm_records_interruption_and_reaps_agent(job, tmp_path):
    pid_file = tmp_path / "agent.pid"
    job.codex_binary.write_text(
        f"#!{sys.executable}\nimport os,time\nfrom pathlib import Path\n"
        f"Path({str(pid_file)!r}).write_text(str(os.getpid()))\ntime.sleep(30)\n"
    )
    config = tmp_path / "job.json"
    config.write_text(job.model_dump_json())
    child = subprocess.Popen(
        [sys.executable, "-m", "token_maxxxer", "headless", "run", "--job-file", str(config)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 15
        while not pid_file.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pid_file.exists()
        child.send_signal(signal.SIGTERM)
        out, err = child.communicate(timeout=5)
        assert child.returncode == 130, (out, err)
        assert json.loads(out)["status"] == "interrupted"
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)
    finally:
        child.kill() if child.poll() is None else None
        child.wait()


def test_cron_install_is_idempotent_and_preserves_unrelated_entries(job, tmp_path, monkeypatch):
    import token_maxxxer.headless_cron as cron

    original = "# Existing backup\n15 3 * * * /usr/local/bin/backup\n"
    contents = [original]
    writes = []
    monkeypatch.setattr(cron, "_read_crontab", lambda: contents[0])

    def write(command, **kwargs):
        assert command == ["crontab", "-"]
        contents[0] = kwargs["input"]
        writes.append(contents[0])
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(cron.subprocess, "run", write)
    path = tmp_path / "job with spaces%literal.yaml"
    assert manage_cron(job, path, "install")["installed"]
    assert contents[0].startswith(original)
    assert "\\%literal" in contents[0]
    assert str(Path(sys.executable).absolute()) in contents[0]
    assert "--scheduled" in contents[0]
    assert "Europe/Paris" in contents[0]
    assert (job.state_directory / "previous-crontab.txt").read_text() == original
    manage_cron(job, path, "install")
    assert len(writes) == 1
    assert manage_cron(job, path, "status")["installed"]
    assert not manage_cron(job, path, "remove")["installed"]
    assert contents[0] == original


@pytest.mark.parametrize(
    "text",
    [
        "# BEGIN token_maxxxer:cards\nmissing end\n",
        "# END token_maxxxer:cards\n# BEGIN token_maxxxer:cards\n",
        "# BEGIN token_maxxxer:cards\n# END token_maxxxer:cards\n" * 2,
    ],
)
def test_malformed_cron_markers_cannot_remove_other_jobs(text):
    with pytest.raises(ValueError, match="markers"):
        replace_block(text, "cards", "")


def test_cron_permission_error_is_not_treated_as_an_empty_crontab(monkeypatch):
    import token_maxxxer.headless_cron as cron

    calls = []

    def denied(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="Operation not permitted")

    monkeypatch.setattr(cron.subprocess, "run", denied)
    with pytest.raises(ValueError, match="cannot read"):
        cron._read_crontab()
    assert calls == [["crontab", "-l"]]


def test_cron_rejects_newline_in_environment(job, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin\n* * * * * unexpected")
    with pytest.raises(ValueError, match="control characters"):
        cron_block(job, tmp_path / "job.yaml")


def test_scheduled_cli_records_actual_invocation_but_preview_writes_nothing(job, tmp_path):
    from token_maxxxer.cli import main

    config = tmp_path / "job.json"
    config.write_text(job.model_dump_json())
    command = ["headless", "run", "--job-file", str(config), "--scheduled"]
    assert main([*command, "--dry-run"]) == 0
    assert not job.state_directory.exists()
    # A zero-length exclusive marker prevents native execution regardless of wall clock.
    today = datetime.now(UTC).astimezone(ZoneInfo(job.timezone)).date()
    yesterday = today - timedelta(days=1)
    for day in (today, yesterday):
        attempt = job.state_directory / "runs" / day.isoformat() / "attempted"
        attempt.parent.mkdir(parents=True)
        attempt.touch()
    assert main(command) == 0
    assert "checked_at" in read_record(job.state_directory / "last-tick.json")


def test_launchagent_lifecycle_preserves_other_services_and_uses_stable_python(
    job, tmp_path, monkeypatch
):
    import plistlib

    import token_maxxxer.headless_launchd as service

    monkeypatch.setattr(service.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    loaded = [False]
    calls = []

    def launchctl(*arguments, required=True):
        calls.append(arguments)
        if arguments[0] == "bootstrap":
            loaded[0] = True
        elif arguments[0] == "bootout":
            loaded[0] = False
        return loaded[0]

    monkeypatch.setattr(service, "_launchctl", launchctl)
    path = tmp_path / "Library/LaunchAgents/com.token-maxxxer.headless.cards.plist"
    other = path.with_name("other.service.plist")
    other.parent.mkdir(parents=True)
    other.write_text("Unrelated service")
    job_file = tmp_path / "job.yaml"
    installed = service.manage_launchd(job, job_file, "install")
    assert installed["installed"] and installed["loaded"]
    plist = plistlib.loads(path.read_bytes())
    assert plist["ProgramArguments"][0] == str(Path(sys.executable).absolute())
    assert plist["ProgramArguments"][-1] == "--scheduled"
    assert plist["RunAtLoad"] and plist["StartInterval"] == 60
    assert not plist["KeepAlive"]
    assert plist["Umask"] == 0o077
    assert path.stat().st_mode & 0o777 == 0o600
    assert service.manage_launchd(job, job_file, "status")["loaded"]
    assert not service.manage_launchd(job, job_file, "remove")["installed"]
    assert other.read_text() == "Unrelated service"
    assert [call[0] for call in calls].count("bootstrap") == 1
    assert [call[0] for call in calls].count("bootout") == 1


def test_launchagent_restores_previous_service_if_bootstrap_fails(job, tmp_path, monkeypatch):
    import token_maxxxer.headless_launchd as service

    monkeypatch.setattr(service.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = tmp_path / "Library/LaunchAgents/com.token-maxxxer.headless.cards.plist"
    path.parent.mkdir(parents=True)
    path.write_text("Previous service")
    bootstraps = []

    def launchctl(*arguments, required=True):
        if arguments[0] == "bootstrap":
            bootstraps.append(arguments)
            if len(bootstraps) == 1:
                raise ValueError("fixture bootstrap failure")
        return True

    monkeypatch.setattr(service, "_launchctl", launchctl)
    with pytest.raises(ValueError, match="fixture bootstrap failure"):
        service.manage_launchd(job, tmp_path / "job.yaml", "install")
    assert path.read_text() == "Previous service"
    assert len(bootstraps) == 2


def test_launchagent_rejects_unsupported_platform(job, tmp_path, monkeypatch):
    import token_maxxxer.headless_launchd as service

    monkeypatch.setattr(service.sys, "platform", "linux")
    with pytest.raises(ValueError, match="only on macOS"):
        service.manage_launchd(job, tmp_path / "job.yaml", "install")
