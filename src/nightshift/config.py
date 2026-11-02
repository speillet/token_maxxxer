"""Configuration validation; loading never creates directories or databases."""

from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, StringConstraints, field_validator, model_validator

from nightshift.models import Model, resolve_path
from nightshift.yaml_io import load_yaml

Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ClockTime = Annotated[str, StringConstraints(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")]
PositiveSeconds = Annotated[int, Field(strict=True, ge=1, le=86400)]


class Window(Model):
    days: Annotated[tuple[Day, ...], Field(min_length=1)]
    start: ClockTime
    end: ClockTime

    @model_validator(mode="after")
    def unambiguous_window(self) -> "Window":
        if len(set(self.days)) != len(self.days):
            raise ValueError("les jours d'un créneau doivent être uniques")
        if self.start == self.end:
            raise ValueError("début et fin doivent être différents")
        return self

    def duration_seconds(self) -> int:
        def seconds(clock: str) -> int:
            hour, minute = map(int, clock.split(":"))
            return hour * 3600 + minute * 60

        return (seconds(self.end) - seconds(self.start)) % 86400


class ScheduleConfig(Model):
    windows: Annotated[tuple[Window, ...], Field(min_length=1)]
    stop_policy: Literal["strict"] = "strict"
    shutdown_grace_seconds: Annotated[int, Field(strict=True, ge=0, le=300)] = 10

    @model_validator(mode="after")
    def grace_fits_window(self) -> "ScheduleConfig":
        if any(window.duration_seconds() <= self.shutdown_grace_seconds for window in self.windows):
            raise ValueError("le délai de grâce doit être inférieur à la durée de chaque créneau")
        return self


class ExecutionConfig(Model):
    concurrency: Literal[1] = 1
    task_timeout_minutes: Annotated[int, Field(strict=True, ge=1, le=1440)] = 30
    verification_timeout_seconds: PositiveSeconds = 300
    max_attempts_per_task: Annotated[int, Field(strict=True, ge=1, le=20)] = 3
    max_active_minutes_per_window: Annotated[int, Field(strict=True, ge=1, le=1440)] = 240
    retry_backoff_seconds: Annotated[
        tuple[PositiveSeconds, ...], Field(min_length=1, max_length=20)
    ] = (
        300,
        900,
        1800,
    )

    @field_validator("retry_backoff_seconds")
    @classmethod
    def increasing_backoff(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if tuple(sorted(value)) != value:
            raise ValueError("les délais de reprise doivent être croissants")
        return value


class AuthenticationConfig(Model):
    mode: Literal["claude_subscription"] = "claude_subscription"
    reject_api_configuration: Literal[True] = True


class GitConfig(Model):
    worktree_per_task: Literal[True] = True
    auto_merge: Literal[False] = False


class RepositoriesConfig(Model):
    allowed: Annotated[tuple[Path, ...], Field(min_length=1)]

    _resolve_allowed = field_validator("allowed")(
        lambda paths, info: tuple(resolve_path(path, info) for path in paths)
    )

    @field_validator("allowed")
    @classmethod
    def existing_unique_directories(cls, paths: tuple[Path, ...]) -> tuple[Path, ...]:
        if any(not path.is_dir() for path in paths):
            raise ValueError("chaque dépôt autorisé doit être un répertoire existant")
        if len(set(paths)) != len(paths):
            raise ValueError("les dépôts autorisés doivent être uniques après résolution des liens")
        return paths


class StorageConfig(Model):
    database: Path = Path("./var/nightshift.sqlite")
    checkpoints: Path = Path("./var/checkpoints.sqlite")
    reports: Path = Path("./var/reports")

    _resolve_paths = field_validator("database", "checkpoints", "reports")(resolve_path)

    @model_validator(mode="after")
    def distinct_paths(self) -> "StorageConfig":
        if self.database.is_relative_to(self.checkpoints) or self.checkpoints.is_relative_to(
            self.database
        ):
            raise ValueError(
                "les bases applicative et LangGraph doivent être distinctes et non imbriquées"
            )
        for database in (self.database, self.checkpoints):
            if database.is_dir() or database == self.reports or database in self.reports.parents:
                raise ValueError(
                    "un chemin de base SQLite ne peut pas être un répertoire de rapports"
                )
            if database.is_relative_to(self.reports):
                raise ValueError("les bases SQLite doivent être séparées du répertoire de rapports")
        if self.reports.exists() and not self.reports.is_dir():
            raise ValueError("reports doit désigner un répertoire")
        for path in (self.database, self.checkpoints, self.reports):
            parent = path.parent
            while not parent.exists() and parent != parent.parent:
                parent = parent.parent
            if not parent.is_dir():
                raise ValueError("le parent d'un emplacement de stockage doit être un répertoire")
        return self


class Config(Model):
    timezone: str = "Europe/Paris"
    schedule: ScheduleConfig
    repositories: RepositoriesConfig
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    authentication: AuthenticationConfig = Field(default_factory=AuthenticationConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    storage: StorageConfig

    @model_validator(mode="before")
    @classmethod
    def storage_defaults(cls, value: object) -> object:
        # Validate the default through the nested model so it receives source-path context.
        if isinstance(value, dict):
            return {"storage": {}, **value}
        return value

    @field_validator("timezone")
    @classmethod
    def iana_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("fuseau IANA inconnu") from exc
        return value


def load_config(path: Path) -> Config:
    path = path.expanduser().resolve()
    return Config.model_validate(load_yaml(path), context={"base_directory": path.parent})
