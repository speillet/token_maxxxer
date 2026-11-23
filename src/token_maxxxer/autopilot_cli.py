"""Overnight roadmap autopilot commands and their daily schedulers."""

import argparse
import json
from collections import Counter
from pathlib import Path

from token_maxxxer.autopilot import AutopilotJob, load_autopilot_job, load_progress, run_autopilot
from token_maxxxer.headless_cron import manage_cron
from token_maxxxer.headless_launchd import manage_launchd
from token_maxxxer.local_state import read_record, write_record
from token_maxxxer.models import utc_now


def add_commands(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    autopilot = commands.add_parser(
        "autopilot",
        help="run native agents overnight on a roadmap, trusted issues and maintenance",
    )
    actions = autopilot.add_subparsers(dest="autopilot_action", required=True)
    run = actions.add_parser("run", help="run tonight's agents until the configured stop time")
    run.add_argument("--job-file", type=Path, required=True)
    run.add_argument("--scheduled", action="store_true", help="respect the daily start window")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="preview the plan without writes, model access or network requests",
    )
    status = actions.add_parser("status", help="summarize the latest night and item progress")
    status.add_argument("--job-file", type=Path, required=True)
    for scheduler in ("cron", "launchd"):
        service = actions.add_parser(
            scheduler, help=f"install, inspect or remove {scheduler} scheduling"
        )
        service.add_argument("action", choices=("install", "status", "remove"))
        service.add_argument("--job-file", type=Path, required=True)


def night_summary(job: AutopilotJob, record: dict[str, object]) -> dict[str, object]:
    """A compact view of a night record, without check output or agent summaries."""
    summary = {
        key: record[key]
        for key in ("status", "reason", "date", "deadline", "source_commit", "roadmap", "issues")
        if key in record
    }
    lanes = record.get("lanes")
    cycles = record.get("cycles")
    summary["lanes"] = [
        {
            "agent": lane.get("agent"),
            "branch": lane.get("branch"),
            "status": lane.get("status"),
            "reason": lane.get("reason"),
            "commits": len(lane.get("commits") or []),
            "worktree_retained": bool(lane.get("worktree_retained")),
        }
        for lane in (lanes if isinstance(lanes, list) else [])
        if isinstance(lane, dict)
    ]
    if isinstance(cycles, list):
        outcomes = Counter(str(cycle.get("outcome")) for cycle in cycles if isinstance(cycle, dict))
        summary["cycles"] = dict(sorted(outcomes.items()))
    if "date" in record:
        summary["report"] = str(job.state_directory / "runs" / str(record["date"]) / "report.md")
    return summary


def autopilot_status(job: AutopilotJob) -> dict[str, object]:
    """Read-only: the latest night, item progress and the scheduler heartbeat."""
    runs = job.state_directory / "runs"
    nights = (
        sorted(
            child.name
            for child in runs.iterdir()
            if child.is_dir() and not child.is_symlink() and (child / "night.json").is_file()
        )
        if runs.is_dir()
        else []
    )
    latest = read_record(runs / nights[-1] / "night.json") if nights else None
    progress = load_progress(job) if (job.state_directory / "progress.json").exists() else {}
    items = progress.get("items", {})
    tick = job.state_directory / "last-tick.json"
    return {
        "job": job.name,
        "nights": len(nights),
        "latest": night_summary(job, latest) if isinstance(latest, dict) else None,
        "items": dict(sorted(Counter(str(item.get("status")) for item in items.values()).items())),
        "lanes": progress.get("lanes", {}),
        "last_tick": read_record(tick) if tick.exists() else None,
    }


def execute(arguments: argparse.Namespace) -> int:
    job = load_autopilot_job(arguments.job_file)
    action = arguments.autopilot_action
    if action in ("cron", "launchd"):
        manager = manage_cron if action == "cron" else manage_launchd
        result = manager(job, arguments.job_file, arguments.action, "autopilot")
    elif action == "status":
        result = autopilot_status(job)
    else:
        if arguments.scheduled and not arguments.dry_run:
            write_record(
                job.state_directory / "last-tick.json", {"checked_at": utc_now().isoformat()}
            )
        result = run_autopilot(job, scheduled=arguments.scheduled, dry_run=arguments.dry_run)
        if arguments.scheduled and result["status"] == "skipped":
            return 0
        if result["status"] not in ("preview", "skipped"):
            result = night_summary(job, result)
    print(json.dumps(result, ensure_ascii=True))
    return 130 if result.get("status") == "interrupted" else int(result.get("status") == "failed")
