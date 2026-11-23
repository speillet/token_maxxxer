"""Manage one marked cron entry while preserving all unrelated user jobs."""

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from token_maxxxer.local_state import read_record, write_private_text
from token_maxxxer.scheduling import ScheduledJob

# Scheduled job kinds map to their `token_maxxxer KIND run --scheduled` command.
JOB_KINDS = ("headless", "autopilot")


def _read_crontab() -> str:
    result = subprocess.run(
        ["crontab", "-l"],
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "LC_ALL": "C"},
        check=False,
    )
    if result.returncode == 0:
        return result.stdout
    if result.returncode == 1 and "no crontab for" in result.stderr.lower():
        return ""
    raise ValueError("cannot read the user crontab; no changes were made")


def scheduled_environment(job: ScheduledJob) -> dict[str, str]:
    if any(char in os.environ.get("PATH", "") for char in "\n\r\x00"):
        raise ValueError("cron paths and environment must not contain control characters")
    directories = [str(Path(sys.executable).parent), str(job.codex_binary.parent)]
    commands = (*job.tool_commands(), ("uv",), ("git",), ("gh",))
    for tool_command in commands:
        if tool_command and (executable := shutil.which(tool_command[0])):
            directories.append(str(Path(executable).parent))
    directories.extend(
        ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")
    )
    environment = {"PATH": ":".join(dict.fromkeys(directories))}
    for name in ("HOME", "CODEX_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        if name in os.environ:
            environment[name] = os.environ[name]
    if any(char in value for value in environment.values() for char in "\n\r\x00"):
        raise ValueError("scheduler paths and environment must not contain control characters")
    return environment


def _kind(kind: str) -> str:
    if kind not in JOB_KINDS:
        raise ValueError("unsupported scheduled job kind")
    return kind


def marker_name(job: ScheduledJob, kind: str = "headless") -> str:
    # Headless keeps its original marker so existing installations remain removable.
    return job.name if _kind(kind) == "headless" else f"{kind}:{job.name}"


def cron_block(job: ScheduledJob, job_file: Path, kind: str = "headless") -> str:
    # Keep the virtualenv path: resolving its Python symlink loses installed packages.
    environment = [f"{name}={value}" for name, value in scheduled_environment(job).items()]
    name = marker_name(job, kind)
    command = shlex.join(
        [
            "/usr/bin/env",
            *environment,
            str(Path(sys.executable).absolute()),
            "-m",
            "token_maxxxer",
            kind,
            "run",
            "--job-file",
            str(job_file.expanduser().resolve()),
            "--scheduled",
        ]
    )
    command += f" >> {shlex.quote(str(job.state_directory / 'cron.log'))} 2>&1"
    if any(char in command for char in "\n\r\x00"):
        raise ValueError("cron paths and environment must not contain control characters")
    # Cron treats percent signs specially even inside shell quotes.
    command = command.replace("%", "\\%")
    return (
        f"# BEGIN token_maxxxer:{name}\n"
        f"# Daily at {job.daily_at} {job.timezone}; Python gates timezone and duplicate attempts.\n"
        f"* * * * * {command}\n"
        f"# END token_maxxxer:{name}\n"
    )


def replace_block(current: str, name: str, block: str) -> str:
    begin, end = f"# BEGIN token_maxxxer:{name}", f"# END token_maxxxer:{name}"
    lines = current.splitlines()
    if lines.count(begin) != lines.count(end) or lines.count(begin) > 1:
        raise ValueError("ambiguous cron markers; no changes were made")
    if begin in lines and lines.index(begin) >= lines.index(end):
        raise ValueError("invalid cron markers; no changes were made")
    pattern = rf"^{re.escape(begin)}\n.*?^{re.escape(end)}(?:\n|$)"
    remaining = re.sub(pattern, "", current, flags=re.MULTILINE | re.DOTALL)
    return remaining + ("\n" if remaining and not remaining.endswith("\n") else "") + block


def manage_cron(
    job: ScheduledJob, job_file: Path, action: str, kind: str = "headless"
) -> dict[str, object]:
    name = marker_name(job, kind)
    current = _read_crontab()
    installed = f"# BEGIN token_maxxxer:{name}" in current.splitlines()
    if action == "status":
        return {
            "installed": installed,
            "daily_at": job.daily_at,
            "timezone": job.timezone,
            "job_file": str(job_file.resolve()),
            "state_directory": str(job.state_directory),
            "last_tick": read_record(job.state_directory / "last-tick.json")
            if (job.state_directory / "last-tick.json").exists()
            else None,
        }
    block = cron_block(job, job_file, kind) if action == "install" else ""
    updated = replace_block(current, name, block)
    if updated != current:
        write_private_text(job.state_directory / "previous-crontab.txt", current)
        result = subprocess.run(
            ["crontab", "-"],
            input=updated,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError("crontab rejected the update; previous crontab was backed up")
    return {"installed": action == "install", "daily_at": job.daily_at, "timezone": job.timezone}
