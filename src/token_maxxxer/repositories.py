"""Bounded local repository discovery and recent-path suggestions."""

import os
import subprocess
from collections import deque
from contextlib import suppress
from pathlib import Path
from urllib.parse import unquote, urlparse

from pydantic import Field

from token_maxxxer.local_state import read_record, write_record
from token_maxxxer.models import Model, UtcDatetime, utc_now

_SKIP = {"node_modules", "vendor", "dist", "build", "venv", "__pycache__"}


def git(
    repository: Path,
    *arguments: str,
    timeout: float = 15,
    allowed_returncodes: tuple[int, ...] = (0,),
) -> str:
    """Run a fixed Git operation without hooks, prompting, a shell or user-facing stderr."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "-C",
                str(repository),
                *arguments,
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
        if result.returncode not in allowed_returncodes:
            raise ValueError("Git operation failed; check the repository and branch state")
        return result.stdout.decode("utf-8")
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise ValueError("Git is unavailable or the local repository cannot be read") from exc


def local_path(value: str) -> Path:
    if value.startswith("file:"):
        parsed = urlparse(value)
        if parsed.netloc not in ("", "localhost") or parsed.query or parsed.fragment:
            raise ValueError("expected a local file:// URL without query or fragment")
        value = unquote(parsed.path)
    elif "://" in value:
        raise ValueError("enter a local repository path; remote URLs are not cloned")
    return Path(value).expanduser().resolve()


def repository_root(path: Path, *, exact: bool = True) -> Path:
    path = path.expanduser().resolve()
    if not path.is_dir():
        raise ValueError("the repository path must be an existing directory")
    root = Path(git(path, "rev-parse", "--show-toplevel").strip()).resolve()
    if exact and root != path:
        raise ValueError("select the Git repository root, rather than a subdirectory")
    return root


class RecentRepository(Model):
    path: Path
    last_used: UtcDatetime
    skill: str | None = None


class RepositoryHistory(Model):
    schema_version: int = Field(default=1, ge=1, le=1)
    repositories: tuple[RecentRepository, ...] = Field(default=(), max_length=50)


def load_history(state: Path) -> RepositoryHistory:
    path = state / "history.json"
    return (
        RepositoryHistory.model_validate(read_record(path))
        if path.exists()
        else RepositoryHistory()
    )


def remember_repository(state: Path, repository: Path, skill: str) -> None:
    previous = load_history(state)
    recent = RecentRepository(path=repository, last_used=utc_now(), skill=skill)
    entries = (recent, *(entry for entry in previous.repositories if entry.path != repository))[:50]
    write_record(
        state / "history.json", RepositoryHistory(repositories=entries).model_dump(mode="json")
    )


def discover_repositories(roots: tuple[Path, ...], *, depth: int = 2) -> list[Path]:
    pending = deque((root.expanduser().resolve(), 0) for root in roots)
    seen: set[Path] = set()
    found: list[Path] = []
    while pending and len(seen) < 2000 and len(found) < 200:
        path, level = pending.popleft()
        if path in seen or not path.is_dir():
            continue
        seen.add(path)
        if (path / ".git").exists():
            with suppress(ValueError):
                found.append(repository_root(path))
            continue
        if level >= depth:
            continue
        try:
            with os.scandir(path) as children:
                # Avoid sorting or materializing an unbounded directory listing.
                for index, child in enumerate(children):
                    if index >= 2000 or len(pending) >= 2000:
                        break
                    if (
                        not child.name.startswith(".")
                        and child.name not in _SKIP
                        and child.is_dir(follow_symlinks=False)
                    ):
                        pending.append((Path(child.path), level + 1))
        except OSError:
            continue
    return sorted(set(found))


def repository_suggestions(
    roots: tuple[Path, ...], allowed: tuple[Path, ...], history: RepositoryHistory
) -> list[Path]:
    candidates = [entry.path for entry in history.repositories]
    candidates.extend(allowed)
    with suppress(ValueError):
        candidates.append(repository_root(Path.cwd(), exact=False))
    candidates.extend(discover_repositories(roots))
    result: list[Path] = []
    for path in candidates:
        if path in result or not path.is_dir():
            continue
        try:
            result.append(repository_root(path))
        except ValueError:
            continue
    return result
