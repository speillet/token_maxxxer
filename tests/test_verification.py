import os
import sys

from token_maxxxer.verification import MAX_LOG_BYTES, run_verification


def test_verification_hides_credentials_and_bounds_output(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fixture-private-value")
    command = (
        sys.executable,
        "-c",
        "import os; "
        "assert 'ANTHROPIC_API_KEY' not in os.environ; "
        "print('sk-fixture-private-value'); print('x' * 100000)",
    )
    result = run_verification(command, tmp_path, 5)
    assert result["status"] == "passed"
    assert result["output_truncated"] is True
    assert len(result["output"]) <= MAX_LOG_BYTES
    assert "sk-fixture-private-value" not in result["output"]


def test_timeout_terminates_the_owned_process_group(tmp_path) -> None:
    pid_file = tmp_path / "child.pid"
    code = (
        "import subprocess,sys,time; from pathlib import Path; "
        "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        f"Path({str(pid_file)!r}).write_text(str(child.pid)); time.sleep(30)"
    )
    result = run_verification((sys.executable, "-c", code), tmp_path, 0.5)
    assert result["status"] == "timeout"
    # killpg must have terminated the child as well as the direct command.
    pid = int(pid_file.read_text())
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    # Some Linux runners retain an adopted zombie briefly; it must not be running.
    status = run_verification(("ps", "-o", "stat=", "-p", str(pid)), tmp_path, 2)
    assert not status["output"].strip() or status["output"].strip().startswith("Z")


def test_missing_verification_executable_has_safe_failure(tmp_path) -> None:
    result = run_verification(("/missing/token_maxxxer-command",), tmp_path, 1)
    assert result["status"] == "failed"
    assert result["exit_code"] is None
