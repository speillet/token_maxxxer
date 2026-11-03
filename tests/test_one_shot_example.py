import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from token_maxxxer.config import ProviderConfig
from token_maxxxer.local_state import write_record
from token_maxxxer.night import NightPlan


@pytest.fixture
def launcher():
    path = Path(__file__).parents[1] / "examples/run_night_once.py"
    specification = importlib.util.spec_from_file_location("one_shot_example", path)
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    yield module
    sys.modules.pop(specification.name)


@pytest.fixture
def launch_request(launcher, repository, tmp_path):
    directory = tmp_path / "launch"
    directory.mkdir()
    skill = directory / "SKILL.md"
    skill.write_text("---\nname: fixture\n---\nReview existing notes.\n", encoding="utf-8")
    commit = subprocess.check_output(
        ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
    ).strip()
    request = launcher.OneShotRequest(
        plan=NightPlan(
            repository=repository,
            skill="file:fixture",
            provider=ProviderConfig(model="fixture-model"),
            hours=1,
        ),
        skill_file=skill,
        env_file=directory / ".env",
        state_directory=tmp_path / "state",
        starts_at=datetime.fromtimestamp(100, UTC),
        ends_at=datetime.fromtimestamp(200, UTC),
        base_commit=commit,
    )
    path = directory / "request.json"
    write_record(path, request.model_dump(mode="json"))
    return path


def install_fakes(launcher, monkeypatch):
    observed = []

    def credential(*args, **kwargs):
        assert kwargs["keychain_timeout_seconds"] == 120
        observed.append("credential")
        return SecretStr("sk-fixture-private-value")

    def run(plan, skill, state, provider, secret, progress, stop_at):
        assert stop_at == 200
        observed.append(plan)
        assert secret.get_secret_value() == "sk-fixture-private-value"
        session = SimpleNamespace(
            id="fixture-session", calls=2, state="completed", reason="skill_completed"
        )
        progress(session)
        return session

    monkeypatch.setattr(launcher, "create_provider", lambda _: object())
    monkeypatch.setattr(launcher, "resolve_credential", credential)
    monkeypatch.setattr(launcher, "run_night", run)
    return observed


def test_secret_is_loaded_before_wait_and_run_is_bounded_to_closing_time(
    launcher, launch_request, monkeypatch
) -> None:
    observed = install_fakes(launcher, monkeypatch)
    now = [0.0]

    def sleep(seconds):
        assert observed == ["credential"]
        status = json.loads((launch_request.parent / "status.json").read_text())
        assert status["phase"] == "scheduled"
        assert 0 < seconds <= 30
        now[0] += seconds

    assert launcher.run_once(launch_request, clock=lambda: now[0], sleep=sleep) == 0
    assert len(observed) == 2
    assert observed[1].hours == 100 / 3600
    status = json.loads((launch_request.parent / "status.json").read_text())
    assert status["phase"] == "completed"
    assert status["calls"] == 2
    assert "sk-fixture-private-value" not in (launch_request.parent / "status.json").read_text()


def test_expired_launch_never_resolves_a_secret_or_runs(
    launcher, launch_request, monkeypatch
) -> None:
    def forbidden(*args):
        raise AssertionError("expired jobs must not access a credential or provider")

    monkeypatch.setattr(launcher, "resolve_credential", forbidden)
    monkeypatch.setattr(launcher, "create_provider", forbidden)
    assert launcher.run_once(launch_request, clock=lambda: 300) == 0
    assert json.loads((launch_request.parent / "status.json").read_text())["phase"] == "expired"


def test_supervisor_restart_does_not_replay_an_attempt(
    launcher, launch_request, monkeypatch
) -> None:
    install_fakes(launcher, monkeypatch)
    assert launcher.run_once(launch_request, clock=lambda: 150) == 0
    previous = (launch_request.parent / "status.json").read_bytes()
    assert launcher.run_once(launch_request, clock=lambda: 150) == 2
    assert (launch_request.parent / "status.json").read_bytes() == previous


def test_credential_failure_preserves_only_its_type(launcher, launch_request, monkeypatch) -> None:
    install_fakes(launcher, monkeypatch)

    def failure(*args, **kwargs):
        raise RuntimeError("sk-fixture-private-value")

    monkeypatch.setattr(launcher, "resolve_credential", failure)
    assert launcher.run_once(launch_request, clock=lambda: 0) == 1
    status = (launch_request.parent / "status.json").read_text()
    assert json.loads(status)["exception"] == "RuntimeError"
    assert "sk-fixture-private-value" not in status


@pytest.mark.parametrize("wakeup", [150, 250])
def test_late_wakeup_reduces_duration_or_expires(
    launcher, launch_request, monkeypatch, wakeup
) -> None:
    observed = install_fakes(launcher, monkeypatch)
    now = [0.0]

    def sleep(seconds):
        now[0] = wakeup

    assert launcher.run_once(launch_request, clock=lambda: now[0], sleep=sleep) == 0
    status = json.loads((launch_request.parent / "status.json").read_text())
    if wakeup < 200:
        assert observed[1].hours == 50 / 3600
    else:
        assert observed == ["credential"]
        assert status["phase"] == "expired"


def test_changed_source_is_not_executed(launcher, launch_request, monkeypatch) -> None:
    observed = install_fakes(launcher, monkeypatch)
    monkeypatch.setattr(launcher, "git", lambda *args: "f" * 40)
    assert launcher.run_once(launch_request, clock=lambda: 150) == 1
    assert observed == []


def test_interrupt_during_wait_persists_cancellation(launcher, launch_request, monkeypatch) -> None:
    observed = install_fakes(launcher, monkeypatch)

    def sleep(seconds):
        raise KeyboardInterrupt

    assert launcher.run_once(launch_request, clock=lambda: 0, sleep=sleep) == 130
    assert observed == ["credential"]
    assert json.loads((launch_request.parent / "status.json").read_text())["phase"] == "cancelled"


def test_status_failure_never_exposes_an_original_credential_error(
    launcher, launch_request, monkeypatch, capsys
) -> None:
    install_fakes(launcher, monkeypatch)
    writer = launcher.write_record

    def fail_credential(*args, **kwargs):
        raise RuntimeError("sk-fixture-private-value")

    def fail_status(path, value):
        if value["phase"] == "failed":
            raise OSError("Simulated full disk.")
        writer(path, value)

    monkeypatch.setattr(launcher, "resolve_credential", fail_credential)
    monkeypatch.setattr(launcher, "write_record", fail_status)
    assert launcher.run_once(launch_request, clock=lambda: 0) == 1
    assert "sk-fixture-private-value" not in capsys.readouterr().err


def test_delay_after_remaining_calculation_cannot_launch_after_closing(
    launcher, launch_request, monkeypatch
) -> None:
    from token_maxxxer.night import run_night

    install_fakes(launcher, monkeypatch)
    now = [150.0]
    git = launcher.git
    probes = []

    def delayed_git(*arguments, **kwargs):
        probes.append(arguments)
        if len(probes) == 2:
            now[0] = 250
        return git(*arguments, **kwargs)

    class ForbiddenProvider:
        def generate(self, *args):
            raise AssertionError("the closed window must not reach a provider")

    def actual_run(*args, **kwargs):
        return run_night(*args, **kwargs, clock=lambda: now[0])

    monkeypatch.setattr(launcher, "git", delayed_git)
    monkeypatch.setattr(launcher, "create_provider", lambda _: ForbiddenProvider())
    monkeypatch.setattr(launcher, "run_night", actual_run)
    assert launcher.run_once(launch_request, clock=lambda: now[0]) == 0
    assert json.loads((launch_request.parent / "status.json").read_text())["phase"] == "expired"


def test_preloaded_credential_skips_keychain(launcher, launch_request, monkeypatch) -> None:
    observed = install_fakes(launcher, monkeypatch)

    def forbidden(*args, **kwargs):
        raise AssertionError("a preloaded credential must not reenter Keychain")

    monkeypatch.setattr(launcher, "resolve_credential", forbidden)
    assert (
        launcher.run_once(
            launch_request, clock=lambda: 150, credential=SecretStr("sk-fixture-private-value")
        )
        == 0
    )
    assert len(observed) == 1


def test_pipe_handoff_preserves_secret_without_exposing_arguments(
    launcher, launch_request, monkeypatch
) -> None:
    captured = []

    def spawn(arguments, **options):
        captured.append((arguments, options, os.dup(options["pass_fds"][0])))
        return SimpleNamespace(pid=123)

    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    key = SecretStr("sk-fixture-private-value")
    assert launcher._detach(launch_request, key) == 123
    arguments, options, received = captured[0]
    assert key.get_secret_value() not in repr(arguments)
    assert "env" not in options
    assert options["start_new_session"] is True
    assert options["stdin"] == subprocess.DEVNULL
    with os.fdopen(received, "rb") as stream:
        assert stream.read() == b"sk-fixture-private-value"
    assert (launch_request.parent / "worker.log").read_bytes() == b""


def test_pipe_credential_accepts_only_bounded_pipe_input(launcher, launch_request) -> None:
    request = launcher.OneShotRequest.model_validate_json(launch_request.read_text())
    read_end, write_end = os.pipe()
    os.write(write_end, b"sk-fixture-private-value")
    os.close(write_end)
    credential = launcher._pipe_credential(request, read_end)
    assert credential.get_secret_value() == "sk-fixture-private-value"
    with launch_request.open("rb") as stream, pytest.raises(ValueError, match="pipe"):
        launcher._pipe_credential(request, os.dup(stream.fileno()))
    for raw in (b"", b"x" * 4097):
        read_end, write_end = os.pipe()
        os.write(write_end, raw)
        os.close(write_end)
        with pytest.raises(ValueError):
            launcher._pipe_credential(request, read_end)


def test_main_masked_prompt_hands_off_only_in_memory(
    launcher, launch_request, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(launcher.time, "time", lambda: 150)
    monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        launcher.sys,
        "argv",
        ["launcher", "--request-file", str(launch_request), "--prompt-key", "--detach"],
    )
    monkeypatch.setattr(launcher.getpass, "getpass", lambda _: "sk-fixture-private-value")
    captured = []

    def detach(path, credential):
        captured.append(credential)
        return 123

    monkeypatch.setattr(launcher, "_detach", detach)
    assert launcher.main() == 0
    assert captured[0].get_secret_value() == "sk-fixture-private-value"
    output = capsys.readouterr()
    assert "sk-fixture-private-value" not in output.out + output.err
    assert "sk-fixture-private-value" not in (launch_request.parent / "status.json").read_text()
    assert not (launch_request.parent / "attempted").exists()


def test_main_refuses_prompt_when_echo_cannot_be_disabled(
    launcher, launch_request, monkeypatch, capsys
) -> None:
    import warnings

    monkeypatch.setattr(launcher.time, "time", lambda: 150)
    monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(
        launcher.sys, "argv", ["launcher", "--request-file", str(launch_request), "--prompt-key"]
    )

    def unavailable_echo(prompt):
        warnings.warn("Cannot hide terminal input", launcher.getpass.GetPassWarning, stacklevel=1)
        raise AssertionError("must refuse before reading with echo enabled")

    monkeypatch.setattr(launcher.getpass, "getpass", unavailable_echo)
    assert launcher.main() == 1
    assert "GetPassWarning" in capsys.readouterr().err
    assert not (launch_request.parent / "attempted").exists()


def test_main_refuses_a_nonterminal_key_prompt(launcher, launch_request, monkeypatch) -> None:
    monkeypatch.setattr(launcher.time, "time", lambda: 150)
    monkeypatch.setattr(launcher.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(
        launcher.sys, "argv", ["launcher", "--request-file", str(launch_request), "--prompt-key"]
    )
    assert launcher.main() == 1
    assert not (launch_request.parent / "attempted").exists()
