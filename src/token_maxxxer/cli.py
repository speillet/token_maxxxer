"""User commands for the foundation milestone. Real execution is deliberately gated."""

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from token_maxxxer.config import load_config
from token_maxxxer.doctor import checks_as_dicts, diagnose
from token_maxxxer.queue import import_document, preview_next
from token_maxxxer.storage import TaskStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="token_maxxxer", description="token_maxxxer — socle local"
    )
    parser.add_argument("--config", type=Path, default=Path("token_maxxxer.yaml"))
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="diagnostic sans inférence ni modification")
    doctor.add_argument("--json", action="store_true")
    tasks = commands.add_parser("tasks", help="file de tâches explicites")
    task_commands = tasks.add_subparsers(dest="task_command", required=True)
    importer = task_commands.add_parser("import", help="importer un YAML de confiance")
    importer.add_argument("path", type=Path)
    importer.add_argument("--json", action="store_true")
    listing = task_commands.add_parser("list", help="lister par priorité puis arrivée")
    listing.add_argument("--json", action="store_true")
    run = commands.add_parser("run", help="simuler la prochaine tâche sans l'acquérir")
    run.add_argument(
        "--dry-run",
        action="store_true",
        required=True,
        help="seule la simulation est disponible dans ce jalon",
    )
    run.add_argument("--json", action="store_true")
    return parser


def _execute(arguments: argparse.Namespace) -> int:
    config = load_config(arguments.config)
    store = TaskStore(config.storage.database)
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
                else f"{inserted} tâche(s) importée(s), {unchanged} inchangée(s)."
            )
        else:
            records = store.list_tasks()
            if arguments.json:
                print(json.dumps([record.model_dump(mode="json") for record in records]))
            elif not records:
                print("File vide.")
            else:
                for task_record in records:
                    print(
                        f"{task_record.task.id}\t{task_record.status.value}"
                        f"\tpriorité={task_record.task.priority}"
                    )
        return 0
    record = preview_next(config, store)
    plan = {
        "dry_run": True,
        "execution_enabled": False,
        "schedule_evaluated": False,
        "reason": "simulation de sélection ; exécuteur au jalon 2 et planning au jalon 5",
        "task": record.task.model_dump(mode="json") if record else None,
        "status": record.status.value if record else None,
    }
    if arguments.json:
        print(json.dumps(plan))
    else:
        print(f"Prochaine tâche : {record.task.id}" if record else "File vide.")
        print(plan["reason"])
        print("Aucun lancement ni changement d'état.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        return _execute(arguments)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2
