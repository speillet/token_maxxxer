"""Versioned application SQLite storage, separate from LangGraph checkpoints."""

import sqlite3
from contextlib import closing
from pathlib import Path

from token_maxxxer.models import Task, TaskRecord, TaskStatus, utc_now

APPLICATION_ID = 0x4E534654  # NSFT
SCHEMA_VERSION = 1
INITIAL_SCHEMA = (
    """CREATE TABLE tasks (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        id TEXT NOT NULL UNIQUE,
        definition_json TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN (
            'pending', 'running', 'waiting_limit', 'paused_schedule',
            'needs_review', 'succeeded', 'failed', 'cancelled'
        )),
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX tasks_selection ON tasks(status, sequence)",
    """CREATE TABLE attempts (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(id),
        payload_json TEXT NOT NULL
    )""",
    "CREATE INDEX attempts_task ON attempts(task_id)",
    """CREATE TABLE usage_observations (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id TEXT REFERENCES attempts(id),
        payload_json TEXT NOT NULL
    )""",
)


class StorageError(ValueError):
    """An actionable storage/schema error."""


class TaskConflictError(StorageError):
    """A stable task ID was reused for a different task definition."""


def _connect(path: Path, *, readonly: bool) -> sqlite3.Connection:
    connection = sqlite3.connect(
        path.as_uri() + "?mode=ro" if readonly else str(path),
        timeout=5,
        uri=readonly,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _schema_metadata(connection: sqlite3.Connection) -> tuple[int, int]:
    return (
        connection.execute("PRAGMA application_id").fetchone()[0],
        connection.execute("PRAGMA user_version").fetchone()[0],
    )


def _require_current_schema(connection: sqlite3.Connection) -> None:
    if _schema_metadata(connection) != (APPLICATION_ID, SCHEMA_VERSION):
        raise StorageError("incompatible SQLite schema; read operations do not migrate databases")


def _migrate(connection: sqlite3.Connection) -> None:
    """Run the initial migration atomically; never adopt an unrelated SQLite database."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        application_id, version = _schema_metadata(connection)
        if (application_id, version) == (APPLICATION_ID, SCHEMA_VERSION):
            connection.commit()
            return
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if application_id != 0 or version != 0 or tables:
            raise StorageError("unknown SQLite database or incompatible version; import refused")
        for statement in INITIAL_SCHEMA:
            connection.execute(statement)
        connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


class TaskStore:
    def __init__(self, database: Path):
        self.database = database.expanduser().resolve()

    def import_tasks(self, tasks: tuple[Task, ...]) -> tuple[int, int]:
        """Insert an entire batch, or roll it all back on an ID conflict."""
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(_connect(self.database, readonly=False)) as connection:
            _migrate(connection)
            inserted = unchanged = 0
            connection.execute("BEGIN IMMEDIATE")
            try:
                for task in tasks:
                    existing = connection.execute(
                        "SELECT definition_json FROM tasks WHERE id = ?", (task.id,)
                    ).fetchone()
                    if existing:
                        if Task.model_validate_json(existing["definition_json"]) != task:
                            raise TaskConflictError(
                                f"task {task.id} already has a different definition; use a new id"
                            )
                        unchanged += 1
                        continue
                    connection.execute(
                        "INSERT INTO tasks (id, definition_json, status, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            task.id,
                            task.model_dump_json(),
                            TaskStatus.PENDING.value,
                            utc_now().isoformat(),
                        ),
                    )
                    inserted += 1
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return inserted, unchanged

    def list_tasks(self) -> list[TaskRecord]:
        """A missing database represents an empty queue; reading creates nothing."""
        if not self.database.exists():
            return []
        with closing(_connect(self.database, readonly=True)) as connection:
            _require_current_schema(connection)
            rows = connection.execute(
                "SELECT definition_json, status, created_at FROM tasks ORDER BY sequence"
            ).fetchall()
        records = [
            TaskRecord(
                task=Task.model_validate_json(row["definition_json"]),
                status=TaskStatus(row["status"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]
        # Python's sort is stable: equal priorities preserve persisted arrival order.
        return sorted(records, key=lambda record: -record.task.priority)
