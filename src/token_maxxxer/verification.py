"""Execute only user-supplied argument arrays with bounded capture and group cleanup."""

import os
import re
import selectors
import signal
import subprocess
import time
from contextlib import suppress
from pathlib import Path

from token_maxxxer.redaction import redact

_SECRET_VARIABLE = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE)
MAX_LOG_BYTES = 16_384


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


def run_verification(command: tuple[str, ...], root: Path, timeout: float) -> dict[str, object]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not _SECRET_VARIABLE.search(key) and not key.startswith("GIT_")
    }
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError:
        return {"status": "failed", "exit_code": None, "output": "Cannot start verification."}
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
                    remaining = MAX_LOG_BYTES - len(captured)
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
    return {
        "status": "timeout" if timed_out else "passed" if process.returncode == 0 else "failed",
        "exit_code": process.returncode,
        "output": redact(captured.decode("utf-8", errors="replace")),
        "output_truncated": truncated,
    }
