"""Trusted YAML task import and read-only selection; acquisition comes in milestone 4."""

from pathlib import Path
from typing import Annotated

from pydantic import Field

from token_maxxxer.config import Config
from token_maxxxer.models import Model, Task, TaskRecord, TaskStatus
from token_maxxxer.storage import TaskStore
from token_maxxxer.yaml_io import DocumentError, load_yaml


class TaskDocument(Model):
    tasks: Annotated[tuple[Task, ...], Field(max_length=10000)]


def require_authorized(task: Task, config: Config) -> None:
    repository = task.repository.resolve()
    if repository not in config.repositories.allowed or not repository.is_dir():
        raise DocumentError(f"repository is not allowed or is missing for task {task.id}")


def import_document(path: Path, config: Config, store: TaskStore) -> tuple[int, int]:
    path = path.expanduser().resolve()
    document = TaskDocument.model_validate(load_yaml(path), context={"base_directory": path.parent})
    ids = [task.id for task in document.tasks]
    if len(ids) != len(set(ids)):
        raise DocumentError("duplicate task identifiers in the document")
    for task in document.tasks:
        require_authorized(task, config)
    return store.import_tasks(document.tasks)


def preview_next(config: Config, store: TaskStore) -> TaskRecord | None:
    """Select only pending work, without acquiring it or changing its status."""
    for record in store.list_tasks():
        if record.status == TaskStatus.PENDING:
            require_authorized(record.task, config)
            return record
    return None
