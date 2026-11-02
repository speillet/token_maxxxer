"""Read-only diagnostics; no inference, credential extraction or account changes."""

import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from nightshift.authentication import API_CONFIGURATION_VARIABLES
from nightshift.config import Config
from nightshift.json_io import load_unique_json
from nightshift.storage import TaskStore


@dataclass(frozen=True)
class Check:
    name: str
    status: Literal["ok", "warning", "error"]
    message: str


def _probe(arguments: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None


def _writable_ancestor(path: Path) -> bool:
    ancestor = path
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    return ancestor.is_dir() and os.access(ancestor, os.W_OK | os.X_OK)


def diagnose(config: Config) -> list[Check]:
    checks = [
        Check("python", "ok", f"Python {sys.version_info.major}.{sys.version_info.minor}"),
        Check("configuration", "ok", "configuration valide ; aucune exécution activée"),
    ]
    git = shutil.which("git")
    if not git:
        checks.append(Check("git", "error", "Git introuvable dans PATH"))
    else:
        result = _probe([git, "--version"])
        valid = result is not None and result.returncode == 0
        checks.append(
            Check(
                "git",
                "ok" if valid else "error",
                "Git disponible" if valid else "Git ne répond pas",
            )
        )
        for repository in config.repositories.allowed:
            result = _probe([git, "-C", str(repository), "rev-parse", "--show-toplevel"])
            valid = (
                result is not None
                and result.returncode == 0
                and Path(result.stdout.strip()).resolve() == repository
            )
            checks.append(
                Check(
                    f"repository:{repository}",
                    "ok" if valid else "error",
                    "racine Git autorisée"
                    if valid
                    else "le chemin doit être une racine Git existante",
                )
            )

    incompatible = [name for name in API_CONFIGURATION_VARIABLES if os.environ.get(name)]
    checks.append(
        Check(
            "authentication_environment",
            "error" if incompatible else "ok",
            "variables incompatibles : " + ", ".join(incompatible)
            if incompatible
            else "aucune variable API ou fournisseur incompatible détectée",
        )
    )
    claude = shutil.which("claude")
    if not claude:
        checks.append(Check("claude", "error", "CLI Claude introuvable dans PATH"))
    else:
        version = _probe([claude, "--version"])
        match = re.match(r"^(\d+\.\d+\.\d+)\b", version.stdout) if version else None
        valid = version is not None and version.returncode == 0 and match is not None
        checks.append(
            Check(
                "claude_version",
                "ok" if valid else "error",
                f"version détectée : {match.group(1)} (non qualifiée)"
                if valid and match
                else "version Claude illisible",
            )
        )
        result = _probe([claude, "auth", "status"])
        authenticated = False
        if result is not None and result.returncode == 0:
            try:
                status = load_unique_json(result.stdout)
                authenticated = (
                    isinstance(status, dict)
                    and status.get("loggedIn") is True
                    and status.get("authMethod") == "claude.ai"
                )
            except (ValueError, RecursionError):
                pass
        checks.append(
            Check(
                "claude_authentication",
                "ok" if authenticated else "error",
                "connexion claude.ai détectée"
                if authenticated
                else "connexion abonnement non confirmée ; utiliser claude auth login",
            )
        )

    for label, path in (
        ("database", config.storage.database),
        ("checkpoints", config.storage.checkpoints),
        ("reports", config.storage.reports),
    ):
        writable = _writable_ancestor(path.parent)
        if path.exists():
            writable = writable and os.access(path, os.W_OK)
        checks.append(
            Check(
                label,
                "ok" if writable else "error",
                "emplacement accessible (aucune création)"
                if writable
                else "emplacement non accessible",
            )
        )
    # Validate existing schema without migrating, creating or changing task status.
    if config.storage.database.exists():
        TaskStore(config.storage.database).list_tasks()
    checks.extend(
        (
            Check(
                "extra_usage", "warning", "crédits supplémentaires : vérifier le réglage du compte"
            ),
            Check(
                "repository_audit", "warning", "hooks, MCP et settings à auditer avant le jalon 2"
            ),
            Check("execution_gate", "warning", "jalon 0 à qualifier ; exécuteur réel indisponible"),
        )
    )
    return checks


def checks_as_dicts(checks: list[Check]) -> list[dict[str, str]]:
    return [asdict(check) for check in checks]
