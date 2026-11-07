"""Run approved checks with bounded, redacted diagnostics."""

import os
import re
from pathlib import Path

from token_maxxxer.commands import run_command
from token_maxxxer.redaction import redact

_SECRET_VARIABLE = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE)
MAX_LOG_BYTES = 16_384


def run_verification(command: tuple[str, ...], root: Path, timeout: float) -> dict[str, object]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not _SECRET_VARIABLE.search(key) and not key.startswith("GIT_")
    }
    environment["GIT_TERMINAL_PROMPT"] = "0"
    result = run_command(
        command, root, timeout, environment, max_output_bytes=MAX_LOG_BYTES, combine_stderr=True
    )
    if result.exit_code is None:
        return {"status": "failed", "exit_code": None, "output": "Cannot start verification."}
    return {
        "status": "timeout"
        if result.timed_out
        else "passed"
        if result.exit_code == 0
        else "failed",
        "exit_code": result.exit_code,
        "output": redact(result.output.decode("utf-8", errors="replace")),
        "output_truncated": result.truncated,
    }
