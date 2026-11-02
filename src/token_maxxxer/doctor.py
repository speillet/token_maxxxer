"""Read-only diagnostics; no inference, credential extraction or account changes."""

import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from token_maxxxer.config import Config
from token_maxxxer.credentials import credential_configured
from token_maxxxer.storage import TaskStore


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
        Check("configuration", "ok", "configuration valide ; aucune requête API effectuée"),
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

    supported = config.provider.name in ("claude", "openai")
    checks.append(
        Check(
            "provider",
            "ok" if supported else "error",
            f"{config.provider.name} / {config.provider.model}"
            if supported
            else "Copilot : intégration SDK prévue, adaptateur indisponible",
        )
    )
    configured = credential_configured(config.provider, config.authentication.env_file)
    checks.append(
        Check(
            "credential_configuration",
            "ok" if configured else "error",
            "clé ou référence configurée (non résolue, non authentifiée)"
            if configured
            else "clé ou référence absente pour le fournisseur sélectionné",
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
    checks.append(
        Check(
            "execution_gate",
            "warning",
            "query génère du texte ; exécution automatique de code à raccorder",
        )
    )
    return checks


def checks_as_dicts(checks: list[Check]) -> list[dict[str, str]]:
    return [asdict(check) for check in checks]
