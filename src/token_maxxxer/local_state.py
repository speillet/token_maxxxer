"""Small private, atomic local records; independent of the task-queue database."""

import json
import os
import tempfile
from pathlib import Path

from token_maxxxer.json_io import load_unique_json


def default_state_directory() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return base.expanduser().resolve() / "token_maxxxer"


def read_record(path: Path) -> object:
    if path.is_symlink():
        raise ValueError("local records must not be symbolic links")
    with path.open(encoding="utf-8") as stream:
        raw = stream.read(4_194_305)
    if len(raw) > 4_194_304:
        raise ValueError("local record is too large")
    return load_unique_json(raw)


def write_record(path: Path, value: object) -> None:
    write_private_text(path, json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2) + "\n")


def write_private_text(path: Path, content: str) -> None:
    """Replace a record atomically with mode 0600, retaining the previous file on error."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".record-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
