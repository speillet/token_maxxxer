"""Run one explicit, bounded night plan under a local process supervisor.

This example is a one-shot launcher, not a recurring scheduler or crash-replay
service. Its JSON request contains credential references only. Load the secret
while the user is present, then keep it in memory until the selected start time.
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import Literal

from pydantic import Field, model_validator

from token_maxxxer.credentials import resolve_credential
from token_maxxxer.local_state import read_record, write_record
from token_maxxxer.models import Model, UtcDatetime, utc_now
from token_maxxxer.night import NightPlan, NightSession, run_night
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


def run_once(
    request_file: Path,
    *,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    request = OneShotRequest.model_validate(read_record(request_file))
    directory = request_file.parent
    if directory.resolve().is_relative_to(request.plan.repository.resolve()):
        raise ValueError("launcher records must be outside the selected repository")
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
            plan, skill, request.state_directory, provider, credential, progress=progress
        )
        update(
            session.state,
            session_id=session.id,
            calls=session.calls,
            reason=session.reason,
            report=str(request.state_directory / "runs" / session.id / "report.md"),
        )
        return 130 if session.state == "interrupted" else 1 if session.state == "failed" else 0
    except KeyboardInterrupt:
        update("cancelled")
        return 130
    except Exception as error:
        # Exception text and raw provider output can contain source or secrets.
        update("failed", exception=type(error).__name__)
        return 1
    finally:
        if awake is not None:
            awake.terminate()
            try:
                awake.wait(timeout=2)
            except subprocess.TimeoutExpired:
                awake.kill()
                awake.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-file", required=True, type=Path)
    arguments = parser.parse_args()

    def terminate(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    return run_once(arguments.request_file.expanduser().resolve())


if __name__ == "__main__":
    raise SystemExit(main())
