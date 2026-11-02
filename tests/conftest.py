from pathlib import Path

import pytest

from token_maxxxer.models import Task


@pytest.fixture
def task(tmp_path: Path) -> Task:
    return Task(
        id="demo-task",
        repository=tmp_path,
        base_ref="main",
        prompt="Ajouter la validation des entrées.",
        acceptance_criteria=("Les tests passent.",),
        verification_commands=(("python", "-m", "pytest"),),
    )


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        "timezone: Europe/Paris\n"
        "provider:\n  name: claude\n  model: fixture-model\n"
        "repositories:\n  allowed: [.]\n"
        "schedule:\n  windows:\n"
        "    - days: [mon]\n      start: '22:00'\n      end: '07:00'\n",
        encoding="utf-8",
    )
    return path
