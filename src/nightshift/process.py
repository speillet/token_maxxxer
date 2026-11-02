"""Bounded POSIX subprocess execution with process-group cleanup on every exit."""

import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProcessCapture:
    exit_code: int | None
    stdout: str = field(default="", repr=False)
    stderr: str = field(default="", repr=False)
    duration_seconds: float = 0
    timed_out: bool = False
    output_exceeded: bool = False
    launch_failed: bool = False
    invalid_encoding: bool = False


def _signal_group(pid: int, signum: int) -> bool:
    try:
        os.killpg(pid, signum)
    except ProcessLookupError:
        return False
    return True


def _stop_group(process: subprocess.Popen[bytes], grace_seconds: float) -> None:
    if _signal_group(process.pid, signal.SIGTERM):
        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline:
            # Reap the leader while also giving its descendants time to terminate.
            process.poll()
            if not _signal_group(process.pid, 0):
                break
            time.sleep(min(0.01, max(0, deadline - time.monotonic())))
        _signal_group(process.pid, signal.SIGKILL)
    process.wait(timeout=5)


def run_process(
    arguments: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    input_text: str = "",
    timeout_seconds: float,
    grace_seconds: float = 0.2,
    max_output_bytes: int = 1_048_576,
) -> ProcessCapture:
    """Capture bounded output without pipe deadlocks or retries. No shell is involved."""
    if not arguments or not 0 < timeout_seconds <= 86400 or not 0 <= grace_seconds <= 10:
        raise ValueError("invalid process arguments or timeout bounds")
    if max_output_bytes < 1:
        raise ValueError("max_output_bytes must be positive")
    started = time.monotonic()
    # Temporary files avoid a child keeping stdout/stderr pipes open after its parent exits.
    # They are private, closed on every path and never become application logs.
    with (
        tempfile.TemporaryFile() as stdin,
        tempfile.TemporaryFile() as stdout,
        tempfile.TemporaryFile() as stderr,
    ):
        stdin.write(input_text.encode("utf-8"))
        stdin.seek(0)
        try:
            process = subprocess.Popen(
                list(arguments),
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                cwd=cwd,
                env=environment,
                start_new_session=True,
            )
        except OSError:
            return ProcessCapture(
                exit_code=None,
                launch_failed=True,
                duration_seconds=time.monotonic() - started,
            )
        timed_out = output_exceeded = False
        try:
            deadline = started + timeout_seconds
            while True:
                output_exceeded = any(
                    os.fstat(stream.fileno()).st_size > max_output_bytes
                    for stream in (stdout, stderr)
                )
                if output_exceeded:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                try:
                    process.wait(timeout=min(0.05, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            # Also clean up descendants after a successful parent exit or KeyboardInterrupt.
            _stop_group(process, grace_seconds)
        stdout.seek(0)
        stderr.seek(0)
        output = stdout.read(max_output_bytes + 1)
        errors = stderr.read(max_output_bytes + 1)
        output_exceeded = output_exceeded or any(
            len(value) > max_output_bytes for value in (output, errors)
        )
        invalid_encoding = False
        try:
            output[:max_output_bytes].decode("utf-8")
            errors[:max_output_bytes].decode("utf-8")
        except UnicodeError:
            invalid_encoding = True
        return ProcessCapture(
            exit_code=process.returncode,
            stdout=output[:max_output_bytes].decode("utf-8", errors="replace"),
            stderr=errors[:max_output_bytes].decode("utf-8", errors="replace"),
            duration_seconds=time.monotonic() - started,
            timed_out=timed_out,
            output_exceeded=output_exceeded,
            invalid_encoding=invalid_encoding,
        )
