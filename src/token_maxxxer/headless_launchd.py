"""User LaunchAgent lifecycle for daily jobs on macOS without crontab access."""

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from token_maxxxer.headless_cron import JOB_KINDS, scheduled_environment
from token_maxxxer.local_state import read_record, write_private_text
from token_maxxxer.redaction import redact
from token_maxxxer.scheduling import ScheduledJob


def label(job: ScheduledJob, kind: str = "headless") -> str:
    if kind not in JOB_KINDS:
        raise ValueError("unsupported scheduled job kind")
    return f"com.token-maxxxer.{kind}.{job.name}"


def launchagent(job: ScheduledJob, job_file: Path, kind: str = "headless") -> dict[str, object]:
    return {
        "Label": label(job, kind),
        "ProgramArguments": [
            str(Path(sys.executable).absolute()),
            "-m",
            "token_maxxxer",
            kind,
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


def manage_launchd(
    job: ScheduledJob, job_file: Path, action: str, kind: str = "headless"
) -> dict[str, object]:
    if sys.platform != "darwin":
        raise ValueError(f"launchd scheduling is available only on macOS; use {kind} cron")
    service = label(job, kind)
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{service}"
    path = Path.home() / "Library/LaunchAgents" / f"{service}.plist"
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
            content = plistlib.dumps(launchagent(job, job_file, kind)).decode("utf-8")
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
        "label": service,
        "daily_at": job.daily_at,
        "timezone": job.timezone,
        "job_file": str(job_file.resolve()),
        "state_directory": str(job.state_directory),
        "last_tick": read_record(job.state_directory / "last-tick.json")
        if (job.state_directory / "last-tick.json").exists()
        else None,
    }
