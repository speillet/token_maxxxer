"""User commands for the foundation milestone. Real execution is deliberately gated."""

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from token_maxxxer.config import load_config
from token_maxxxer.credentials import resolve_credential
from token_maxxxer.doctor import checks_as_dicts, diagnose
from token_maxxxer.providers import MAX_PROMPT_CHARACTERS, GenerationRequest, create_provider
from token_maxxxer.queue import import_document, preview_next
from token_maxxxer.storage import TaskStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="token_maxxxer", description="token_maxxxer — local API task toolkit"
    )
    parser.add_argument("--config", type=Path, default=Path("token_maxxxer.yaml"))
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser(
        "doctor", help="diagnose configuration without API requests or changes"
    )
    doctor.add_argument("--json", action="store_true")
    tasks = commands.add_parser("tasks", help="explicit task queue")
    task_commands = tasks.add_subparsers(dest="task_command", required=True)
    importer = task_commands.add_parser("import", help="import trusted YAML")
    importer.add_argument("path", type=Path)
    importer.add_argument("--json", action="store_true")
    listing = task_commands.add_parser("list", help="list tasks by priority and arrival")
    listing.add_argument("--json", action="store_true")
    run = commands.add_parser("run", help="preview the next task without claiming it")
    run.add_argument(
        "--dry-run",
        action="store_true",
        required=True,
        help="only dry-run mode is available at this milestone",
    )
    run.add_argument("--json", action="store_true")
    query = commands.add_parser("query", help="send a prompt to the selected API provider")
    query.add_argument("--prompt-file", type=Path, required=True, help="UTF-8 file, or - for stdin")
    query.add_argument("--json", action="store_true")
    return parser


def _execute(arguments: argparse.Namespace) -> int:
    config = load_config(arguments.config)
    store = TaskStore(config.storage.database)
    if arguments.command == "query":
        if str(arguments.prompt_file) == "-":
            prompt = sys.stdin.read(MAX_PROMPT_CHARACTERS + 1)
        else:
            with arguments.prompt_file.open(encoding="utf-8") as stream:
                prompt = stream.read(MAX_PROMPT_CHARACTERS + 1)
        if len(prompt) > MAX_PROMPT_CHARACTERS:
            raise ValueError("prompt is too large; nothing was sent")
        request = GenerationRequest(prompt=prompt, settings=config.provider)
        provider = create_provider(config.provider)
        credential = resolve_credential(config.provider, config.authentication.env_file)
        result = provider.generate(request, credential)
        if arguments.json:
            print(result.model_dump_json())
        elif result.status == "success":
            print(result.text)
        else:
            print(f"{result.status}: {result.error_code}", file=sys.stderr)
        return 0 if result.status == "success" else 1
    if arguments.command == "doctor":
        checks = diagnose(config)
        if arguments.json:
            print(json.dumps({"checks": checks_as_dicts(checks), "execution_enabled": False}))
        else:
            for check in checks:
                print(f"{check.status.upper():7} {check.name}: {check.message}")
        return int(any(check.status == "error" for check in checks))
    if arguments.command == "tasks":
        if arguments.task_command == "import":
            inserted, unchanged = import_document(arguments.path, config, store)
            print(
                json.dumps({"inserted": inserted, "unchanged": unchanged})
                if arguments.json
                else f"{inserted} task(s) imported, {unchanged} unchanged."
            )
        else:
            records = store.list_tasks()
            if arguments.json:
                print(json.dumps([record.model_dump(mode="json") for record in records]))
            elif not records:
                print("Queue is empty.")
            else:
                for task_record in records:
                    print(
                        f"{task_record.task.id}\t{task_record.status.value}"
                        f"\tpriority={task_record.task.priority}"
                    )
        return 0
    record = preview_next(config, store)
    plan = {
        "dry_run": True,
        "execution_enabled": False,
        "schedule_evaluated": False,
        "provider": {"name": config.provider.name, "model": config.provider.model},
        "reason": "selection preview; code execution and scheduling are not connected",
        "task": record.task.model_dump(mode="json") if record else None,
        "status": record.status.value if record else None,
    }
    if arguments.json:
        print(json.dumps(plan))
    else:
        print(f"Next task: {record.task.id}" if record else "Queue is empty.")
        print(plan["reason"])
        print("Nothing was launched and no state was changed.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        return _execute(arguments)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
