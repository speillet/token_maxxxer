"""Run one explicit, bounded night plan under a local process supervisor.

This example is a one-shot launcher, not a recurring scheduler or crash-replay
service. Its JSON request contains credential references only. Load the secret
while the user is present, then keep it in memory until the selected start time.
"""

import argparse
import getpass
import os
import signal
import stat
import subprocess
import sys
import time
import warnings
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from types import FrameType
from typing import Literal

from pydantic import Field, SecretStr, model_validator

from token_maxxxer.credentials import KEY_VARIABLES, resolve_credential
from token_maxxxer.local_state import read_record, write_record
from token_maxxxer.models import Model, UtcDatetime, utc_now
from token_maxxxer.night import NightPlan, NightSession, NightWindowClosed, run_night
from token_maxxxer.providers import create_provider
from token_maxxxer.repositories import git
from token_maxxxer.skills import load_skill


class OneShotRequest(Model):
    schema_version: Literal[1] = 1
    plan: NightPlan
    skill_file: Path
    env_file: Path
    state_directory: Path
    starts_at: UtcDatetime
    ends_at: UtcDatetime
    base_commit: str = Field(pattern=r"^[a-f0-9]{40}(?:[a-f0-9]{24})?$")
    keep_awake: bool = False

    @model_validator(mode="after")
    def bounded_window(self) -> "OneShotRequest":
        duration = (self.ends_at - self.starts_at).total_seconds()
        if not 0 < duration <= 86400:
            raise ValueError("the one-shot window must last between zero and 24 hours")
        for path in (self.plan.repository, self.skill_file, self.env_file, self.state_directory):
            if not path.is_absolute():
                raise ValueError("supervised requests require absolute paths")
        if self.state_directory.resolve().is_relative_to(self.plan.repository.resolve()):
            raise ValueError("session storage must be outside the repository")
        return self


def _load_request(path: Path) -> OneShotRequest:
    request = OneShotRequest.model_validate(read_record(path))
    if path.parent.resolve().is_relative_to(request.plan.repository.resolve()):
        raise ValueError("launcher records must be outside the selected repository")
    return request


def run_once(
    request_file: Path,
    *,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    credential: SecretStr | None = None,
) -> int:
    request = _load_request(request_file)
    directory = request_file.parent
    # A permanent attempt marker prevents supervisor restarts from replaying work.
    try:
        descriptor = os.open(directory / "attempted", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return 2
    os.close(descriptor)
    status: dict[str, object] = {
        "schema_version": 1,
        "pid": os.getpid(),
        "starts_at": request.starts_at.isoformat(),
        "ends_at": request.ends_at.isoformat(),
        "base_commit": request.base_commit,
        "repository": str(request.plan.repository),
        "provider": request.plan.provider.name,
        "model": request.plan.provider.model,
        "max_calls": request.plan.max_calls,
    }

    def update(phase: str, **values: object) -> None:
        status.update(phase=phase, updated_at=utc_now().isoformat(), **values)
        write_record(directory / "status.json", status)

    awake: subprocess.Popen[bytes] | None = None
    try:
        if clock() >= request.ends_at.timestamp():
            update("expired")
            return 0
        update("authorizing")
        if git(request.plan.repository, "rev-parse", "HEAD").strip() != request.base_commit:
            raise ValueError("the pinned source changed")
        skill = load_skill(request.skill_file)
        if skill.id != request.plan.skill:
            raise ValueError("the selected skill does not match the plan")
        provider = create_provider(request.plan.provider)
        if credential is None:
            credential = resolve_credential(
                request.plan.provider, request.env_file, keychain_timeout_seconds=120
            )
        if request.keep_awake:
            if sys.platform != "darwin":
                raise ValueError("keep_awake requires macOS caffeinate")
            awake = subprocess.Popen(
                ["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        update("scheduled", keep_awake=awake is not None)
        while clock() < request.starts_at.timestamp():
            sleep(min(30, request.starts_at.timestamp() - clock()))
        remaining = request.ends_at.timestamp() - clock()
        if remaining <= 0:
            update("expired")
            return 0
        if git(request.plan.repository, "rev-parse", "HEAD").strip() != request.base_commit:
            raise ValueError("the pinned source changed while waiting")
        hours = min(request.plan.hours, remaining / 3600)
        plan = NightPlan.model_validate({**request.plan.model_dump(), "hours": hours})
        update("running")

        def progress(session: NightSession) -> None:
            update("running", session_id=session.id, calls=session.calls)

        session = run_night(
            plan,
            skill,
            request.state_directory,
            provider,
            credential,
            progress=progress,
            stop_at=request.ends_at.timestamp(),
        )
        update(
            session.state,
            session_id=session.id,
            calls=session.calls,
            reason=session.reason,
            report=str(request.state_directory / "runs" / session.id / "report.md"),
        )
        return 130 if session.state == "interrupted" else 1 if session.state == "failed" else 0
    except NightWindowClosed:
        update("expired")
        return 0
    except KeyboardInterrupt:
        update("cancelled")
        return 130
    except Exception as error:
        # Exception text and raw provider output can contain source or secrets.
        try:
            update("failed", exception=type(error).__name__)
        except Exception:
            # Disk failures must not expose the original exception through chaining.
            print("Cannot persist launch failure status.", file=sys.stderr)
        return 1
    finally:
        if awake is not None:
            awake.terminate()
            try:
                awake.wait(timeout=2)
            except subprocess.TimeoutExpired:
                awake.kill()
                awake.wait()


def _input_credential(request: OneShotRequest, value: str) -> SecretStr:
    if not value:
        raise ValueError("no API key supplied")
    return resolve_credential(
        request.plan.provider,
        request.env_file,
        {KEY_VARIABLES[request.plan.provider.name]: value},
    )


def _pipe_credential(request: OneShotRequest, descriptor: int) -> SecretStr:
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISFIFO(os.fstat(stream.fileno()).st_mode):
            raise ValueError("credential handoff requires an anonymous pipe")
        raw = stream.read(4097)
    if not 0 < len(raw) <= 4096:
        raise ValueError("invalid credential handoff size")
    return _input_credential(request, raw.decode("ascii"))


def _stop_worker(process: subprocess.Popen[bytes]) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def _detach(request_file: Path, credential: SecretStr) -> int:
    read_end, write_end = os.pipe()
    log = -1
    process = None
    try:
        try:
            log = os.open(
                request_file.parent / "worker.log",
                os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
                0o600,
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--request-file",
                    str(request_file),
                    "--credential-fd",
                    str(read_end),
                ],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                pass_fds=(read_end,),
                start_new_session=True,
            )
            # Only the pipe FD appears in argv; the value stays in process/pipe memory.
            raw = credential.get_secret_value().encode("ascii")
            if os.write(write_end, raw) != len(raw):
                raise ValueError("incomplete credential handoff")
        finally:
            os.close(read_end)
            os.close(write_end)
            if log >= 0:
                os.close(log)
    except BaseException:
        if process is not None:
            _stop_worker(process)
        raise
    return process.pid


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-file", required=True, type=Path)
    credential_source = parser.add_mutually_exclusive_group()
    credential_source.add_argument(
        "--prompt-key",
        action="store_true",
        help="read an API key locally with terminal echo disabled",
    )
    credential_source.add_argument("--credential-fd", type=int, help=argparse.SUPPRESS)
    parser.add_argument(
        "--detach",
        action="store_true",
        help="after --prompt-key, hand off the key to a detached worker in memory",
    )
    arguments = parser.parse_args()
    if arguments.detach and not arguments.prompt_key:
        parser.error("--detach requires --prompt-key")

    def terminate(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    previous_term = signal.signal(signal.SIGTERM, terminate)
    prompting = False
    detached_pid = None

    def prompt_outcome(phase: str) -> None:
        if prompting:
            with suppress(Exception):
                write_record(
                    arguments.request_file.expanduser().resolve().parent / "status.json",
                    {"schema_version": 1, "phase": phase},
                )

    try:
        request_file = arguments.request_file.expanduser().resolve()
        request = _load_request(request_file)
        if (request_file.parent / "attempted").exists():
            print("This request was already attempted; inspect its existing status.")
            return 2
        if time.time() >= request.ends_at.timestamp():
            return run_once(request_file)
        credential = None
        if arguments.credential_fd is not None:
            credential = _pipe_credential(request, arguments.credential_fd)
        elif arguments.prompt_key:
            if not sys.stdin.isatty():
                raise ValueError("masked credential input requires a terminal")
            write_record(
                request_file.parent / "status.json",
                {
                    "schema_version": 1,
                    "phase": "waiting_for_local_key",
                    "pid": os.getpid(),
                    "starts_at": request.starts_at.isoformat(),
                    "ends_at": request.ends_at.isoformat(),
                },
            )
            prompting = True
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                value = getpass.getpass(f"{request.plan.provider.name} API key (hidden): ")
            credential = _input_credential(request, value)
            del value
        if arguments.detach:
            assert credential is not None
            detached_pid = _detach(request_file, credential)
            prompting = False
            print(
                f"Worker {detached_pid} launched. "
                f"Check {request_file.parent / 'status.json'} for readiness."
            )
            return 0
        prompting = False
        return run_once(request_file, credential=credential)
    except KeyboardInterrupt:
        if detached_pid is not None:
            print(
                f"Worker {detached_pid} was already handed off; inspect its status.",
                file=sys.stderr,
            )
            return 0
        prompt_outcome("cancelled")
        print("Launch cancelled.", file=sys.stderr)
        return 130
    except Exception as error:
        prompt_outcome("failed")
        print(f"Launch failed ({type(error).__name__}); inspect local storage.", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous_term)


if __name__ == "__main__":
    raise SystemExit(main())
