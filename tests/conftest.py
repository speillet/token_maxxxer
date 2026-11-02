import subprocess
from pathlib import Path

import pytest

from token_maxxxer.models import Task


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "readme.md").write_text("# Example project\n", encoding="utf-8")
    (root / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(
        "Keep changes focused and add useful tests.\n", encoding="utf-8"
    )
    (root / ".gitignore").write_text(".env\nignored.txt\nprivate/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "-qm",
            "Initial fixture",
        ],
        check=True,
    )
    return root


@pytest.fixture
def task(tmp_path: Path) -> Task:
    return Task(
        id="demo-task",
        repository=tmp_path,
        base_ref="main",
        prompt="Add input validation.",
        acceptance_criteria=("The tests pass.",),
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
