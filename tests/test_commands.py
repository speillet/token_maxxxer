import os
import sys
import threading
import time

import pytest

from token_maxxxer.commands import run_command


def test_cancel_event_terminates_the_whole_process_group(tmp_path):
    pid_file = tmp_path / "child.pid"
    script = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(30)\n"
    )
    cancel = threading.Event()
    timer = threading.Timer(0.5, cancel.set)
    timer.start()
    started = time.monotonic()
    try:
        result = run_command(
            [sys.executable, "-c", script], tmp_path, 20, os.environ, cancel=cancel
        )
    finally:
        timer.cancel()
    assert time.monotonic() - started < 5
    assert result.cancelled and not result.timed_out
    assert result.exit_code != 0
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def test_cancel_event_also_stops_a_process_that_closed_its_output(tmp_path):
    cancel = threading.Event()
    timer = threading.Timer(0.3, cancel.set)
    timer.start()
    script = "import os, time\nos.close(1)\ntime.sleep(30)\n"
    try:
        result = run_command(
            [sys.executable, "-c", script], tmp_path, 20, os.environ, cancel=cancel
        )
    finally:
        timer.cancel()
    assert result.cancelled


def test_cancelled_event_prevents_launch(tmp_path):
    marker = tmp_path / "started"
    cancel = threading.Event()
    cancel.set()
    result = run_command(
        [sys.executable, "-c", f"open({str(marker)!r}, 'w')"],
        tmp_path,
        5,
        os.environ,
        cancel=cancel,
    )
    assert result.cancelled and result.exit_code is None
    assert not marker.exists()


def test_uncancelled_command_keeps_its_exit_code_and_output(tmp_path):
    result = run_command(
        [sys.executable, "-c", "print('ready'); raise SystemExit(3)"],
        tmp_path,
        5,
        os.environ,
        cancel=threading.Event(),
    )
    assert (result.exit_code, result.output.strip(), result.cancelled) == (3, b"ready", False)
