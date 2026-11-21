"""Explicit headless skill runs and daily cron lifecycle."""

import argparse
import json
from pathlib import Path

from token_maxxxer.headless import load_job, run_headless
from token_maxxxer.headless_cron import manage_cron
from token_maxxxer.headless_launchd import manage_launchd
from token_maxxxer.local_state import write_record
from token_maxxxer.models import utc_now


def add_commands(commands: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    headless = commands.add_parser("headless", help="run a native Codex skill through LangGraph")
    actions = headless.add_subparsers(dest="headless_action", required=True)
    run = actions.add_parser("run", help="run one subject in a persistent local review branch")
    run.add_argument("--job-file", type=Path, required=True)
    run.add_argument("--scheduled", action="store_true", help="respect the daily start window")
    run.add_argument(
        "--dry-run", action="store_true", help="preview without writes or model access"
    )
    for scheduler in ("cron", "launchd"):
        service = actions.add_parser(
            scheduler, help=f"install, inspect or remove {scheduler} scheduling"
        )
        service.add_argument("action", choices=("install", "status", "remove"))
        service.add_argument("--job-file", type=Path, required=True)


def execute(arguments: argparse.Namespace) -> int:
    job = load_job(arguments.job_file)
    if arguments.headless_action in ("cron", "launchd"):
        manager = manage_cron if arguments.headless_action == "cron" else manage_launchd
        result = manager(job, arguments.job_file, arguments.action)
    else:
        if arguments.scheduled and not arguments.dry_run:
            write_record(
                job.state_directory / "last-tick.json", {"checked_at": utc_now().isoformat()}
            )
        result = run_headless(job, scheduled=arguments.scheduled, dry_run=arguments.dry_run)
        if arguments.scheduled and result["status"] == "skipped":
            return 0
        if result["status"] != "preview":
            result = {key: value for key, value in result.items() if key != "checks"}
    print(json.dumps(result, ensure_ascii=True))
    return 130 if result.get("status") == "interrupted" else int(result.get("status") == "failed")
