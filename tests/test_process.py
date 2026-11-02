import os
import signal
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest

from token_maxxxer.process import _signal_group, run_process


def test_prompt_and_arguments_are_literal_without_a_shell(tmp_path) -> None:
    marker = tmp_path / "must-not-exist"
    text = f"$(touch {marker}); `touch {marker}`\nUnicode : é"
    result = run_process(
        [sys.executable, "-c", "import sys; print(sys.stdin.read(), end='')"],
        cwd=tmp_path,
        environment={},
        input_text=text,
        timeout_seconds=5,
    )
    assert result.exit_code == 0
    assert result.stdout == text
    assert not marker.exists()


def test_separate_stderr_and_launch_failure(tmp_path) -> None:
    result = run_process(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
        cwd=tmp_path,
        environment={},
        timeout_seconds=5,
    )
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"
    missing = run_process(
        [str(tmp_path / "absent")], cwd=tmp_path, environment={}, timeout_seconds=1
    )
    assert missing.launch_failed and missing.exit_code is None


def test_output_limit_is_detected_even_if_parent_exits_quickly(tmp_path) -> None:
    result = run_process(
        [sys.executable, "-c", "print('x' * 100000)"],
        cwd=tmp_path,
        environment={},
        timeout_seconds=5,
        max_output_bytes=1024,
    )
    assert result.output_exceeded
    assert len(result.stdout.encode()) == 1024


def test_invalid_utf8_is_flagged(tmp_path) -> None:
    result = run_process(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xff')"],
        cwd=tmp_path,
        environment={},
        timeout_seconds=5,
    )
    assert result.invalid_encoding


def test_keyboard_interrupt_still_cleans_up_the_process(tmp_path, monkeypatch) -> None:
    original_wait = subprocess.Popen.wait
    interrupted = False
    started_process = None

    def interrupt_once(process, timeout=None):
        nonlocal interrupted, started_process
        started_process = process
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt
        return original_wait(process, timeout=timeout)

    with monkeypatch.context() as patch:
        patch.setattr(subprocess.Popen, "wait", interrupt_once)
        with pytest.raises(KeyboardInterrupt):
            run_process(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                cwd=tmp_path,
                environment={},
                timeout_seconds=5,
            )
    assert started_process is not None
    assert started_process.poll() is not None
    assert not is_active(started_process.pid)


@pytest.mark.parametrize("exit_code", [None, -15])
def test_macos_group_permission_error_is_ignored_only_after_leader_exit(
    monkeypatch, exit_code
) -> None:
    process = Mock(spec=subprocess.Popen)
    process.pid = 12345
    process.poll.return_value = exit_code

    def denied(*args):
        raise PermissionError("group probe denied")

    monkeypatch.setattr(os, "killpg", denied)
    if exit_code is None:
        with pytest.raises(PermissionError):
            _signal_group(process, 0)
    else:
        assert _signal_group(process, 0) is False


def is_active(pid: int) -> bool:
    result = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return (
        result.returncode == 0
        and bool(result.stdout.strip())
        and not result.stdout.strip().startswith("Z")
    )


@pytest.mark.parametrize("parent_waits", [True, False])
def test_process_group_cleanup_includes_children_ignoring_sigterm(tmp_path, parent_waits) -> None:
    child = tmp_path / "child.py"
    child.write_text(
        "import os, signal, time\nfrom pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "Path('child.pid').write_text(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    parent = tmp_path / "parent.py"
    parent.write_text(
        "import subprocess, sys, time\nfrom pathlib import Path\n"
        "subprocess.Popen([sys.executable, 'child.py'])\n"
        "while not Path('child.pid').exists(): time.sleep(0.01)\n"
        + ("time.sleep(60)\n" if parent_waits else "")
    )
    result = run_process(
        [sys.executable, str(parent)],
        cwd=tmp_path,
        environment={},
        timeout_seconds=1 if parent_waits else 5,
        grace_seconds=0.1,
    )
    child_pid = int((tmp_path / "child.pid").read_text())
    try:
        deadline = time.monotonic() + 3
        while is_active(child_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not is_active(child_pid)
        assert result.timed_out is parent_waits
        assert result.duration_seconds < 5
    finally:
        if is_active(child_pid):
            os.kill(child_pid, signal.SIGKILL)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout_is_rejected_without_launching(tmp_path, timeout) -> None:
    with pytest.raises(ValueError):
        run_process(["absent"], cwd=tmp_path, environment={}, timeout_seconds=timeout)
