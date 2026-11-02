"""Bounded text tools restricted to a selected repository or skill directory."""

import hashlib
import os
import tempfile
from pathlib import Path, PurePosixPath

from token_maxxxer.redaction import redact
from token_maxxxer.repositories import git

MAX_FILE_BYTES = 65_536
_DENIED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".ssh",
    ".aws",
    ".gnupg",
    ".worktrees",
    "worktrees",
    "var",
}
_DENIED_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".pyc",
    ".lock",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".woff",
    ".woff2",
    ".ttf",
    ".mp4",
    ".so",
    ".dylib",
    ".exe",
}


def safe_relative_path(value: str) -> Path:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or any(part.lower() in _DENIED_DIRECTORIES for part in path.parts)
        or any(
            part.lower().startswith((".env", "credentials", "id_rsa", "id_ed25519"))
            for part in path.parts
        )
        or path.suffix.lower() in _DENIED_SUFFIXES
        or path == PurePosixPath(".")
    ):
        raise ValueError("path is outside the permitted text-file tools")
    return Path(*path.parts)


def _checked_path(root: Path, relative: Path) -> Path:
    candidate = root / relative
    if root.is_symlink():
        raise ValueError("tool roots must not be symbolic links")
    for component in (candidate, *candidate.parents):
        if component == root:
            break
        if component.is_symlink():
            raise ValueError("symbolic links are not available to file tools")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("path escapes the tool root")
    return candidate


def _read_text(path: Path) -> tuple[str, bytes]:
    if not path.is_file():
        raise ValueError("expected a regular text file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES or b"\x00" in raw:
        raise ValueError("file is binary or exceeds the 64 KiB tool limit")
    try:
        return raw.decode("utf-8"), raw
    except UnicodeError as exc:
        raise ValueError("file tools require UTF-8 text") from exc


class FileTools:
    def __init__(self, root: Path, *, editable: bool, skill_directory: Path | None = None):
        self.root = root
        self.editable = editable
        self.skill_directory = skill_directory
        self.read_versions: dict[str, bytes] = {}
        self.created: set[str] = set()
        self.changed: set[str] = set()
        self.write_version = 0
        self.catalog: list[str] = []
        ignored = set(
            git(root, "ls-files", "--cached", "--ignored", "--exclude-standard", "-z").split("\x00")
        )
        for name in git(root, "ls-files", "-z").split("\x00"):
            if not name or name in ignored:
                continue
            try:
                relative = safe_relative_path(name)
                path = _checked_path(root, relative)
                if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except ValueError:
                continue
            self.catalog.append(name)
            if len(self.catalog) >= 10_000:
                break

    def list_files(self, prefix: str = "") -> dict[str, object]:
        files = sorted(name for name in {*self.catalog, *self.created} if name.startswith(prefix))
        return {"files": files[:1000], "truncated": len(files) > 1000}

    def read_file(self, value: str) -> str:
        relative = safe_relative_path(value)
        name = relative.as_posix()
        if name not in self.catalog and name not in self.created:
            raise ValueError(
                "only eligible Git-tracked files and session-created files can be read"
            )
        path = _checked_path(self.root, relative)
        content, raw = _read_text(path)
        self.read_versions[name] = hashlib.sha256(raw).digest()
        return redact(content)

    def read_skill_file(self, value: str) -> str:
        if self.skill_directory is None:
            raise ValueError("this skill has no supporting directory")
        path = _checked_path(self.skill_directory, safe_relative_path(value))
        return redact(_read_text(path)[0])

    def repository_instructions(self) -> str:
        parts: list[str] = []
        for name in sorted(self.catalog):
            if Path(name).name == "AGENTS.md":
                parts.append(f"Instructions from {name}:\n{self.read_file(name)}")
                if sum(map(len, parts)) > MAX_FILE_BYTES:
                    raise ValueError("repository instructions exceed the 64 KiB limit")
        return "\n\n".join(parts)

    def write_file(self, value: str, content: str) -> str:
        if not self.editable:
            raise ValueError("review mode does not allow writes")
        relative = safe_relative_path(value)
        name = relative.as_posix()
        path = _checked_path(self.root, relative)
        raw = content.encode("utf-8")
        if len(raw) > MAX_FILE_BYTES or b"\x00" in raw:
            raise ValueError("writes require UTF-8 text no larger than 64 KiB")
        if git(
            self.root, "check-ignore", "--no-index", "--", name, allowed_returncodes=(0, 1)
        ).strip():
            raise ValueError("ignored files cannot be written")
        mode = 0o644
        if path.exists():
            if name not in self.catalog and name not in self.created:
                raise ValueError("existing untracked files cannot be overwritten")
            previous, previous_raw = _read_text(path)
            if name not in self.read_versions:
                raise ValueError("read the current file and its instructions before writing")
            if self.read_versions[name] != hashlib.sha256(previous_raw).digest():
                raise ValueError("file changed since it was read; read it again before writing")
            if redact(previous) != previous:
                raise ValueError("files with detected credentials cannot be overwritten")
            mode = path.stat().st_mode & 0o777
            if previous_raw == raw:
                return "File is unchanged."
        else:
            self.created.add(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        _checked_path(self.root, relative)
        descriptor, temporary = tempfile.mkstemp(prefix=".token-maxxxer-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), mode)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        self.read_versions[name] = hashlib.sha256(raw).digest()
        self.changed.add(name)
        self.write_version += 1
        return "File written in the isolated worktree; verification is still required."
