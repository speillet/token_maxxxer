import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from token_maxxxer.config import load_config
from token_maxxxer.models import TaskStatus
from token_maxxxer.queue import import_document, preview_next
from token_maxxxer.storage import SCHEMA_VERSION, StorageError, TaskConflictError, TaskStore
from token_maxxxer.yaml_io import DocumentError


def write_tasks(path: Path, tasks: list) -> Path:
    path.write_text(yaml.safe_dump({"tasks": [task.model_dump(mode="json") for task in tasks]}))
    return path


def test_import_is_persistent_idempotent_and_sorted(config_path, task) -> None:
    config = load_config(config_path)
    store = TaskStore(config.storage.database)
    tasks = [
        task,
        task.model_copy(update={"id": "high-first", "priority": 10}),
        task.model_copy(update={"id": "high-second", "priority": 10}),
    ]
    document = write_tasks(config_path.parent / "tasks.yaml", tasks)
    assert import_document(document, config, store) == (3, 0)
    assert import_document(document, config, store) == (0, 3)
    records = TaskStore(config.storage.database).list_tasks()
    assert [record.task.id for record in records] == ["high-first", "high-second", "demo-task"]
    assert all(record.status == TaskStatus.PENDING for record in records)
    assert all(record.created_at.utcoffset().total_seconds() == 0 for record in records)


def test_batch_conflict_rolls_back_every_insert(tmp_path, task) -> None:
    store = TaskStore(tmp_path / "queue.sqlite")
    store.import_tasks((task,))
    new = task.model_copy(update={"id": "new"})
    conflict = task.model_copy(update={"prompt": "Different prompt"})
    with pytest.raises(TaskConflictError):
        store.import_tasks((new, conflict))
    assert [record.task for record in store.list_tasks()] == [task]


def test_concurrent_imports_do_not_duplicate_tasks(tmp_path, task) -> None:
    database = tmp_path / "queue.sqlite"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: TaskStore(database).import_tasks((task,)), range(2)))
    assert sorted(results) == [(0, 1), (1, 0)]
    assert len(TaskStore(database).list_tasks()) == 1


@pytest.mark.parametrize("kind", ["duplicate", "unauthorized", "nested"])
def test_invalid_batch_is_rejected_before_database_creation(config_path, task, kind) -> None:
    config = load_config(config_path)
    if kind == "duplicate":
        tasks = [task, task]
    else:
        unauthorized = (
            config_path.parent / "nested" if kind == "nested" else config_path.parent.parent
        )
        unauthorized.mkdir(exist_ok=True)
        tasks = [task, task.model_copy(update={"id": "other", "repository": unauthorized})]
    document = write_tasks(config_path.parent / "tasks.yaml", tasks)
    with pytest.raises(DocumentError):
        import_document(document, config, TaskStore(config.storage.database))
    assert not config.storage.database.parent.exists()


def test_task_repository_is_resolved_from_task_document(config_path, task) -> None:
    config = load_config(config_path)
    document = config_path.parent / "tasks.yaml"
    definition = task.model_dump(mode="json")
    definition["repository"] = "."
    document.write_text(yaml.safe_dump({"tasks": [definition]}))
    store = TaskStore(config.storage.database)
    assert import_document(document, config, store) == (1, 0)
    assert store.list_tasks()[0].task.repository == config_path.parent


def test_preview_does_not_write_and_skips_completed_tasks(config_path, task) -> None:
    config = load_config(config_path)
    store = TaskStore(config.storage.database)
    assert preview_next(config, store) is None
    assert not config.storage.database.parent.exists()
    store.import_tasks((task, task.model_copy(update={"id": "next"})))
    with sqlite3.connect(store.database) as connection:
        connection.execute("UPDATE tasks SET status = 'succeeded' WHERE id = ?", (task.id,))
    before = store.database.read_bytes()
    assert preview_next(config, store).task.id == "next"
    assert store.database.read_bytes() == before
    assert store.import_tasks((task,)) == (0, 1)
    assert store.list_tasks()[0].status == TaskStatus.SUCCEEDED


def test_schema_is_versioned_and_foreign_databases_are_rejected(tmp_path, task) -> None:
    database = tmp_path / "foreign.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER)")
    before = database.read_bytes()
    store = TaskStore(database)
    with pytest.raises(StorageError):
        store.import_tasks((task,))
    assert database.read_bytes() == before
    database = tmp_path / "future.sqlite"
    store = TaskStore(database)
    store.import_tasks((task,))
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(StorageError):
        store.list_tasks()
    with pytest.raises(StorageError):
        store.import_tasks((task,))
