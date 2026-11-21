"""User LaunchAgent lifecycle for daily jobs on macOS without crontab access."""

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from token_maxxxer.headless import HeadlessJob
from token_maxxxer.headless_cron import scheduled_environment
from token_maxxxer.local_state import read_record, write_private_text
from token_maxxxer.redaction import redact


def launchagent(job: HeadlessJob, job_file: Path) -> dict[str, object]:
    return {
        "Label": f"com.token-maxxxer.headless.{job.name}",
        "ProgramArguments": [
            str(Path(sys.executable).absolute()),
            "-m",
            "token_maxxxer",
            "headless",
            "run",
            "--job-file",
            str(job_file.expanduser().resolve()),
            "--scheduled",
        ],
        "EnvironmentVariables": scheduled_environment(job),
        "WorkingDirectory": str(job.state_directory),
        "RunAtLoad": True,
        "StartInterval": 60,
        "KeepAlive": False,
        "ProcessType": "Background",
        "ExitTimeOut": 10,
        "Umask": 0o077,
        "StandardOutPath": str(job.state_directory / "scheduler.log"),
        "StandardErrorPath": str(job.state_directory / "scheduler.log"),
    }


def _launchctl(*arguments: str, required: bool = True) -> bool:
    result = subprocess.run(
        ["/bin/launchctl", *arguments], capture_output=True, text=True, timeout=15, check=False
    )
    if required and result.returncode != 0:
        raise ValueError(f"launchctl failed: {redact(result.stderr.strip())[:500]}")
    return result.returncode == 0


def manage_launchd(job: HeadlessJob, job_file: Path, action: str) -> dict[str, object]:
    if sys.platform != "darwin":
        raise ValueError("launchd scheduling is available only on macOS; use headless cron")
    label = f"com.token-maxxxer.headless.{job.name}"
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{label}"
    path = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
    loaded = _launchctl("print", target, required=False)
    if action != "status":
        previous = path.read_text(encoding="utf-8") if path.exists() else None
        if previous is not None:
            write_private_text(job.state_directory / "previous-launchagent.plist", previous)
        if loaded:
            _launchctl("bootout", target)
        if action == "remove":
            path.unlink(missing_ok=True)
        else:
            job.state_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            content = plistlib.dumps(launchagent(job, job_file)).decode("utf-8")
            write_private_text(path, content)
            try:
                _launchctl("bootstrap", domain, str(path))
            except ValueError:
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    write_private_text(path, previous)
                    if loaded:
                        _launchctl("bootstrap", domain, str(path))
                raise
        loaded = _launchctl("print", target, required=False)
    return {
        "installed": path.exists(),
        "loaded": loaded,
        "label": label,
        "daily_at": job.daily_at,
        "timezone": job.timezone,
        "job_file": str(job_file.resolve()),
        "state_directory": str(job.state_directory),
        "last_tick": read_record(job.state_directory / "last-tick.json")
        if (job.state_directory / "last-tick.json").exists()
        else None,
    }
