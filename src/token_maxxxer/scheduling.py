"""Daily start windows and attempt markers shared by scheduled native-agent jobs."""

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ScheduledJob(Protocol):
    """Configuration needed to gate, install and inspect a daily scheduled job."""

    @property
    def name(self) -> str: ...

    @property
    def state_directory(self) -> Path: ...

    @property
    def codex_binary(self) -> Path: ...

    @property
    def timezone(self) -> str: ...

    @property
    def daily_at(self) -> str: ...

    @property
    def latest_start_minutes(self) -> int: ...

    def tool_commands(self) -> tuple[tuple[str, ...], ...]:
        """Commands whose executables must remain on the scheduler's PATH."""
        ...


def valid_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ValueError("unknown IANA timezone") from error
    return value


def scheduled_date(job: ScheduledJob, now: datetime) -> str | None:
    """Find the daily window in IANA time, including a window crossing midnight."""
    if now.tzinfo is None:
        raise ValueError("the schedule clock must be timezone-aware")
    local = now.astimezone(ZoneInfo(job.timezone))
    hour, minute = map(int, job.daily_at.split(":"))
    for day in (local.date(), local.date() - timedelta(days=1)):
        opening = datetime(day.year, day.month, day.day, hour, minute, tzinfo=local.tzinfo)
        elapsed = local.timestamp() - opening.timestamp()
        if 0 <= elapsed < job.latest_start_minutes * 60:
            return day.isoformat()
    return None


def run_date(job: ScheduledJob, now: datetime, *, scheduled: bool) -> str | None:
    """Return the attempt date: the open daily window, or today for a manual run."""
    if now.tzinfo is None:
        raise ValueError("the schedule clock must be timezone-aware")
    if scheduled:
        return scheduled_date(job, now)
    return now.astimezone(ZoneInfo(job.timezone)).date().isoformat()


def claim_attempt(directory: Path) -> bool:
    """Create the exclusive no-replay marker; False when that date was already attempted."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(directory / "attempted", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    os.close(descriptor)
    return True
