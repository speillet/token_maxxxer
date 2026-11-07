"""Bounded capture and process-group cleanup for trusted argument arrays."""

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None
    output: bytes = b""
    timed_out: bool = False
    truncated: bool = False


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        if sig == signal.SIGTERM:
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=0.2)
    process.wait()


def run_command(
    command: Sequence[str],
    root: Path,
    timeout: float,
    environment: Mapping[str, str],
    *,
    max_output_bytes: int = 262_144,
    combine_stderr: bool = False,
) -> CommandResult:
    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if combine_stderr else subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return CommandResult(exit_code=None)
    captured = bytearray()
    truncated = timed_out = False
    started = time.monotonic()
    assert process.stdout is not None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() - started >= timeout:
                    timed_out = True
                    break
                if process.poll() is not None:
                    _terminate_group(process)
                for key, _ in selector.select(timeout=min(0.1, timeout)):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    remaining = max_output_bytes - len(captured)
                    captured.extend(chunk[:remaining])
                    truncated = truncated or len(chunk) > remaining
            if process.poll() is None and not timed_out:
                try:
                    process.wait(timeout=max(0.001, timeout - (time.monotonic() - started)))
                except subprocess.TimeoutExpired:
                    timed_out = True
    finally:
        _terminate_group(process)
        process.stdout.close()
    return CommandResult(process.returncode, bytes(captured), timed_out, truncated)
