"""LangGraph supervision of a native, bounded Codex skill in a local review branch."""

import fnmatch
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langgraph.graph import END, START, StateGraph
from pydantic import Field, field_validator, model_validator

from token_maxxxer.commands import run_command
from token_maxxxer.config import ClockTime
from token_maxxxer.file_tools import safe_relative_path
from token_maxxxer.local_providers import runtime_environment
from token_maxxxer.local_state import read_record, write_private_text, write_record
from token_maxxxer.models import CommandArgument, Model, TaskId, Text, resolve_path, utc_now
from token_maxxxer.night import _DeadlineReached, _repository_lock, _signals
from token_maxxxer.redaction import redact
from token_maxxxer.repositories import git, repository_root
from token_maxxxer.skills import load_skill
from token_maxxxer.yaml_io import load_yaml


class HeadlessJob(Model):
    schema_version: Literal[1] = 1
    name: TaskId
    repository: Path
    skill_file: Path
    state_directory: Path
    codex_binary: Path
    model: Text
    timezone: str = "Europe/Paris"
    daily_at: ClockTime = "22:00"
    latest_start_minutes: Annotated[int, Field(strict=True, ge=1, le=720)] = 60
    timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=43200)] = 7200
    check_timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=3600)] = 600
    subjects: Annotated[tuple[str, ...], Field(min_length=1)]
    write_paths: Annotated[tuple[str, ...], Field(min_length=1)]
    verification_commands: Annotated[
        tuple[Annotated[tuple[CommandArgument, ...], Field(min_length=1)], ...],
        Field(min_length=1),
    ]
    inventory_command: tuple[CommandArgument, ...] = ()

    _resolve_paths = field_validator("repository", "skill_file", "state_directory", "codex_binary")(
        resolve_path
    )

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("unknown IANA timezone") from error
        return value

    @field_validator("subjects", "write_paths")
    @classmethod
    def relative_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("subject paths and write patterns must be unique")
        for value in values:
            safe_relative_path(value)
        return values

    @model_validator(mode="after")
    def safe_job(self) -> "HeadlessJob":
        if not self.skill_file.is_relative_to(self.repository):
            raise ValueError("the skill must be inside the selected repository")
        if self.state_directory.is_relative_to(self.repository):
            raise ValueError("headless state must be outside the selected repository")
        encoded = json.dumps((self.verification_commands, self.inventory_command))
        if redact(encoded) != encoded:
            raise ValueError("commands must not contain credentials")
        if any(
            "\x00" in argument
            for command in (*self.verification_commands, self.inventory_command)
            for argument in command
        ):
            raise ValueError("commands must not contain NUL")
        return self


def load_job(path: Path) -> HeadlessJob:
    path = path.expanduser().resolve()
    return HeadlessJob.model_validate(load_yaml(path), context={"base_directory": path.parent})


def scheduled_date(job: HeadlessJob, now: datetime) -> str | None:
    """Find the daily window in IANA time, including a window crossing midnight."""
    if now.tzinfo is None:
        raise ValueError("the schedule clock must be timezone-aware")
    local = now.astimezone(ZoneInfo(job.timezone))
    hour, minute = map(int, job.daily_at.split(":"))
    for day in (local.date(), local.date() - timedelta(days=1)):
        opening = datetime(day.year, day.month, day.day, hour, minute, tzinfo=local.tzinfo)
        elapsed = local.timestamp() - opening.timestamp()
        if 0 <= elapsed < job.latest_start_minutes * 60:
            return day.isoformat()
    return None


class _GraphState(TypedDict):
    status: str
    reason: str


class _Run:
    def __init__(self, job: HeadlessJob, date: str):
        self.job = job
        self.date = date
        self.root = job.state_directory / "worktree"
        self.directory = job.state_directory / "runs" / date
        self.progress_path = job.state_directory / "progress.json"
        self.record: dict[str, object] = {
            "date": date,
            "job": job.name,
            "status": "starting",
            "started_at": utc_now().isoformat(),
            "worktree": str(self.root),
            "branch": f"token_maxxxer/headless-{job.name}",
            "checks": [],
        }
        self.checks: list[dict[str, object]] = []
        self.subject_index = 0
        self.subject = job.subjects[0]
        self.deadline = time.monotonic() + job.timeout_seconds
        self.environment = runtime_environment()
        self.environment.update(GIT_TERMINAL_PROMPT="0", LANGSMITH_TRACING="false")

    def save(self, status: str, reason: str = "") -> _GraphState:
        self.record.update(status=status, reason=reason, checks=self.checks)
        write_record(self.directory / "status.json", self.record)
        return {"status": status, "reason": reason}

    def command(self, command: tuple[str, ...], *, agent: bool = False) -> bytes:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("headless_deadline_reached")
        arguments = tuple(
            argument.replace("{inventory_before}", str(self.directory / "inventory-before.json"))
            for argument in command
        )
        result = run_command(
            arguments,
            self.root,
            remaining if agent else min(remaining, self.job.check_timeout_seconds),
            self.environment,
            max_output_bytes=4_194_304
            if agent or command == self.job.inventory_command
            else 65_536,
            combine_stderr=command != self.job.inventory_command,
            input_bytes=self.prompt().encode("utf-8") if agent else None,
        )
        if not agent:
            self.checks.append(
                {
                    "command": list(arguments),
                    "exit_code": result.exit_code,
                    "timed_out": result.timed_out,
                    "output": "Inventory captured separately."
                    if command == self.job.inventory_command
                    else redact(result.output.decode("utf-8", errors="replace")),
                    "truncated": result.truncated,
                }
            )
            self.save(str(self.record["status"]))
        if result.timed_out:
            raise ValueError("agent_timeout" if agent else "verification_timeout")
        if result.exit_code != 0:
            raise ValueError("agent_failed" if agent else "verification_failed")
        if result.truncated:
            raise ValueError("agent_output_too_large" if agent else "verification_output_too_large")
        return result.output

    def prepare(self, state: _GraphState) -> _GraphState:
        job = self.job
        repository_root(job.repository)
        if not job.codex_binary.is_file() or not os.access(job.codex_binary, os.X_OK):
            raise ValueError("codex_binary_unavailable")
        source = git(job.repository, "rev-parse", "HEAD").strip()
        branch = str(self.record["branch"])
        if not self.root.exists():
            exists = git(job.repository, "branch", "--list", branch).strip()
            arguments = () if exists else ("-b", branch)
            git(
                job.repository,
                "worktree",
                "add",
                *arguments,
                str(self.root),
                branch if exists else source,
                timeout=60,
            )
        if git(self.root, "branch", "--show-current").strip() != branch:
            raise ValueError("unexpected_review_branch")
        if git(self.root, "status", "--porcelain=v1", "-z"):
            raise ValueError("review_worktree_needs_attention")
        head = git(self.root, "rev-parse", "HEAD").strip()
        ancestor = git(self.root, "merge-base", source, head).strip()
        if ancestor == head and head != source:
            git(self.root, "merge", "--ff-only", source)
        elif ancestor != source:
            raise ValueError("source_and_review_branch_diverged")
        git(self.root, "var", "GIT_AUTHOR_IDENT")
        if self.progress_path.exists():
            progress = read_record(self.progress_path)
            if not isinstance(progress, dict):
                raise ValueError("invalid_headless_progress")
            self.subject_index = int(str(progress.get("next_subject", 0))) % len(job.subjects)
        self.subject = job.subjects[self.subject_index]
        if not (self.root / self.subject).is_file():
            raise ValueError("review_subject_missing")
        skill_file = self.root / job.skill_file.relative_to(job.repository)
        load_skill(skill_file)
        self.record.update(
            subject=self.subject, base_commit=git(self.root, "rev-parse", "HEAD").strip()
        )
        return self.save("prepared")

    def baseline(self, state: _GraphState) -> _GraphState:
        self.save("baseline")
        if self.job.inventory_command:
            raw = self.command(self.job.inventory_command)
            # An invalid/truncated inventory must fail before the agent is launched.
            json.loads(raw)
            write_private_text(self.directory / "inventory-before.json", raw.decode("utf-8"))
        self.verify_commands()
        if git(self.root, "status", "--porcelain=v1", "-z"):
            raise ValueError("baseline_changed_worktree")
        return self.save("baseline_passed")

    def prompt(self) -> str:
        skill_file = self.root / self.job.skill_file.relative_to(self.job.repository)
        skill = load_skill(skill_file)
        return (
            f"Apply ${skill.name} to this subject: {self.subject}, including its canonical "
            f"reference and related cards. Today is {self.date} in {self.job.timezone}.\n"
            "This is an authorized unattended review in deepen mode. Read AGENTS.md and "
            "the skill's supporting instructions. Audit scientific claims against primary "
            "sources before enriching existing answers. Preserve card IDs, Anki identities, "
            "questions, objectives and learner-authored material. Work continuously on this "
            "one subject, then stop. New cards require a learner decision: register proposals "
            "as pending in the report; do not create cards or wait for an interactive reply.\n"
            "Run the skill's checks. Do not weaken checks, modify scripts or skills, publish, "
            "push, merge, commit, change branches or remove files. The supervisor will verify "
            "and commit valid changes to the local review branch. If a check fails, report it "
            "honestly. Do not claim source access or successful checks without evidence.\n"
            f"Permitted write patterns: {json.dumps(self.job.write_paths)}.\n"
            "The supervisor has already run the configured baseline checks successfully. "
            "It will run them again after you finish; do not report them as your own executions.\n"
            f"Supervisor checks: {json.dumps(self.job.verification_commands)}.\n"
            "Put temporary inventories outside the repository. Finish with a concise account "
            "of changes, consulted sources, checks and unresolved decisions.\n\n"
            f"Skill instructions:\n{skill.instructions}\n"
        )

    def execute(self, state: _GraphState) -> _GraphState:
        self.save("running")
        command = (
            str(self.job.codex_binary),
            "exec",
            "--ephemeral",
            "--sandbox",
            "workspace-write",
            "--color",
            "never",
            "--model",
            self.job.model,
            "-c",
            'approval_policy="never"',
            "-c",
            'web_search="live"',
            "-c",
            "features.multi_agent=false",
            "-c",
            "features.hooks=false",
            "-c",
            "features.apps=false",
            "-c",
            "features.plugins=false",
            "-",
        )
        # Raw tool events and source contents are transient, not persisted in job logs.
        self.command(command, agent=True)
        return self.save("agent_completed")

    def verify_commands(self) -> None:
        for command in self.job.verification_commands:
            self.command(command)

    def verify(self, state: _GraphState) -> _GraphState:
        self.save("verifying")
        if git(self.root, "branch", "--show-current").strip() != self.record["branch"]:
            raise ValueError("agent_changed_branch")
        if git(self.root, "rev-parse", "HEAD").strip() != self.record["base_commit"]:
            raise ValueError("agent_changed_head")
        changed = set(
            filter(None, git(self.root, "diff", "HEAD", "--name-only", "-z").split("\x00"))
        )
        changed.update(
            filter(
                None,
                git(self.root, "ls-files", "--others", "--exclude-standard", "-z").split("\x00"),
            )
        )
        self.record["changed_files"] = sorted(changed)
        if git(self.root, "diff", "HEAD", "--no-renames", "--diff-filter=D", "--name-only"):
            raise ValueError("agent_removed_files")
        for name in changed:
            safe_relative_path(name)
            if (self.root / name).is_symlink() or not any(
                fnmatch.fnmatchcase(name, pattern) for pattern in self.job.write_paths
            ):
                raise ValueError("agent_changed_unapproved_path")
        git(self.root, "diff", "HEAD", "--check")
        before_checks = git(self.root, "diff", "HEAD", "--binary")
        if self.job.inventory_command:
            raw = self.command(self.job.inventory_command)
            json.loads(raw)
            write_private_text(self.directory / "inventory-after.json", raw.decode("utf-8"))
        self.verify_commands()
        if git(self.root, "diff", "HEAD", "--binary") != before_checks:
            raise ValueError("verification_changed_tracked_files")
        return self.save("verified")

    def record_result(self, state: _GraphState) -> _GraphState:
        changed = self.record.get("changed_files", [])
        if isinstance(changed, list) and changed:
            git(self.root, "add", "--", *map(str, changed))
            git(self.root, "diff", "--cached", "--check")
            git(
                self.root,
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-m",
                f"docs(cards): review {Path(self.subject).stem}",
                timeout=60,
            )
        self.record.update(
            commit=git(self.root, "rev-parse", "HEAD").strip(), finished_at=utc_now().isoformat()
        )
        write_record(
            self.progress_path,
            {
                "next_subject": (self.subject_index + 1) % len(self.job.subjects),
                "last_date": self.date,
            },
        )
        return self.save("completed", "needs_review" if changed else "no_changes")

    def run(self) -> dict[str, object]:
        graph = StateGraph(_GraphState)
        for name, action in (
            ("prepare", self.prepare),
            ("baseline", self.baseline),
            ("execute", self.execute),
            ("verify", self.verify),
            ("record", self.record_result),
        ):
            graph.add_node(name, action)
        for before, after in (
            (START, "prepare"),
            ("prepare", "baseline"),
            ("baseline", "execute"),
            ("execute", "verify"),
            ("verify", "record"),
            ("record", END),
        ):
            graph.add_edge(before, after)
        try:
            with _signals(max(0.001, self.deadline - time.monotonic())):
                graph.compile().invoke({"status": "starting", "reason": ""})
        except _DeadlineReached:
            self.save("failed", "headless_deadline_reached")
        except KeyboardInterrupt:
            self.save("interrupted", "interrupted_by_signal")
        except Exception as error:
            # Only known error codes are safe to persist, never arbitrary provider text.
            reason = str(error) if isinstance(error, ValueError) else "local_operation_failed"
            if not re.fullmatch(r"[a-z_]{1,80}", reason):
                reason = "local_operation_failed"
            self.record["exception"] = type(error).__name__
            self.save("failed", reason)
        return self.record


def run_headless(
    job: HeadlessJob, *, scheduled: bool = False, now: datetime | None = None, dry_run: bool = False
) -> dict[str, object]:
    now = now or utc_now()
    if now.tzinfo is None:
        raise ValueError("the schedule clock must be timezone-aware")
    date = (
        scheduled_date(job, now)
        if scheduled
        else now.astimezone(ZoneInfo(job.timezone)).date().isoformat()
    )
    if date is None:
        return {"status": "skipped", "reason": "outside_start_window"}
    if dry_run:
        return {"status": "preview", "date": date, "job": job.model_dump(mode="json")}
    directory = job.state_directory / "runs" / date
    if (directory / "attempted").exists():
        return {"status": "skipped", "reason": "already_attempted", "date": date}
    with _repository_lock(repository_root(job.repository)):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(
                directory / "attempted", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
        except FileExistsError:
            return {"status": "skipped", "reason": "already_attempted", "date": date}
        os.close(descriptor)
        return _Run(job, date).run()
