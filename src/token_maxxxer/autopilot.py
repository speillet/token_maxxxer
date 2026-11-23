"""Overnight roadmap autopilot: parallel native agents, verified cycles and local commits.

Each configured agent works in its own lane: a dated branch and worktree prepared from the
source HEAD (or from that lane's unmerged previous night). A LangGraph loop selects the next
roadmap item or maintenance pass, runs native Codex, verifies paths, credentials and approved
checks, then commits accepted work locally. Rejected work is saved as a private patch and the
worktree is reset so the night can continue. Nothing is pushed or merged.
"""

import fnmatch
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, TypedDict
from zoneinfo import ZoneInfo

from langgraph.graph import END, START, StateGraph
from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator

from token_maxxxer.commands import run_command
from token_maxxxer.config import ClockTime
from token_maxxxer.file_tools import safe_relative_path
from token_maxxxer.headless import codex_exec_command
from token_maxxxer.json_io import load_unique_json
from token_maxxxer.local_providers import runtime_environment
from token_maxxxer.local_state import read_record, write_private_text, write_record
from token_maxxxer.models import CommandArgument, Model, TaskId, Text, resolve_path, utc_now
from token_maxxxer.night import _DeadlineReached, _repository_lock, _signals
from token_maxxxer.redaction import redact
from token_maxxxer.repositories import git, git_output, repository_root
from token_maxxxer.roadmap import (
    ROADMAP_CANDIDATES,
    Milestone,
    RoadmapItem,
    mark_done,
    parse_roadmap,
    ready_items,
)
from token_maxxxer.scheduling import claim_attempt, run_date, valid_timezone
from token_maxxxer.yaml_io import load_yaml

Source = Literal["roadmap", "maintenance"]
Focus = Literal["security", "tests", "coverage", "refactor", "relevance", "docs", "performance"]
AgentStatus = Literal["done", "partial", "blocked", "no_change"]

# Each maintenance focus maps to a Conventional Commit type and its instructions.
FOCUSES: dict[str, tuple[str, str]] = {
    "security": (
        "fix",
        "Audit the code for vulnerabilities: injection, path traversal, unsafe "
        "deserialization or subprocess use, missing validation at trust boundaries, secrets in "
        "code or logs, and unsafe file permissions. Fix one concrete, evidenced weakness and add "
        "a regression test.",
    ),
    "tests": (
        "test",
        "Find important behavior without meaningful tests, especially error paths and trust "
        "boundaries. Add focused tests, and fix any defect they reveal.",
    ),
    "coverage": (
        "test",
        "Measure test coverage with tooling the project already provides when possible, without "
        "adding dependencies. Raise coverage of the least-covered important module with "
        "meaningful assertions rather than incidental line execution.",
    ),
    "refactor": (
        "refactor",
        "Find duplicated or needlessly complex code. Make one behavior-preserving refactoring "
        "that clearly improves readability or maintainability, protected by tests.",
    ),
    "relevance": (
        "refactor",
        "Find dead code, obsolete options, stale comments, unused dependencies or documentation "
        "that no longer matches behavior. Remove or correct one clear case, with evidence that "
        "it is unused or wrong.",
    ),
    "docs": (
        "docs",
        "Check that the README, guides and docstrings match current behavior and commands. "
        "Correct inaccuracies and document missing user-facing behavior; never document "
        "features that do not exist.",
    ),
    "performance": (
        "perf",
        "Find a measurable inefficiency on a realistic path, such as repeated I/O, quadratic "
        "loops or unbounded memory. Fix it without changing behavior and keep tests passing.",
    ),
}
DEFAULT_PROTECTED_PATHS = (
    ".github/*",
    "AGENTS.md",
    "CLAUDE.md",
    ".agents/*",
    ".claude/*",
    ".codex/*",
)
MAX_CHANGED_FILE_BYTES = 2_097_152
MAX_AGENT_OUTPUT_BYTES = 1_048_576
MAX_SUMMARY_CHARACTERS = 2_000
_REPORT = re.compile(r"^[ \t>*`]*AUTOPILOT_RESULT:\s*(\{.*\})[ \t`*]*$", re.MULTILINE)
_REASON = re.compile(r"[a-z_]{1,80}")
_SECRET_VALUE = re.compile(
    r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{20,}|github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|AKIA[0-9A-Z]{16}|xox[abprs]-[A-Za-z0-9-]{10,})"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
_SECRET_FILE = re.compile(
    r"(?:^|/)(?:\.env(?!\.example$)(?:\.[^/]*)?|\.netrc|_netrc|\.npmrc|\.pypirc|\.pgpass"
    r"|\.git-credentials|id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?|credentials[^/]*\.json)$",
    re.IGNORECASE,
)
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


class AutopilotAgent(Model):
    """One native agent; each runs in its own lane, in parallel with the others."""

    name: TaskId
    model: Text
    sources: tuple[Source, ...] | None = None

    @field_validator("sources")
    @classmethod
    def unique_sources(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is not None and (not value or len(set(value)) != len(value)):
            raise ValueError("agent sources must be nonempty and unique")
        return value


class AutopilotJob(Model):
    schema_version: Literal[1] = 1
    name: TaskId
    repository: Path
    state_directory: Path
    codex_binary: Path
    agents: Annotated[tuple[AutopilotAgent, ...], Field(min_length=1, max_length=4)]
    sources: Annotated[tuple[Source, ...], Field(min_length=1)] = ("roadmap", "maintenance")
    roadmap_file: str | None = None
    maintenance_focuses: Annotated[tuple[Focus, ...], Field(min_length=1)] = (
        "security",
        "tests",
        "coverage",
        "refactor",
        "relevance",
        "docs",
    )
    timezone: str = "Europe/Paris"
    daily_at: ClockTime = "22:00"
    latest_start_minutes: Annotated[int, Field(strict=True, ge=1, le=720)] = 60
    stop_at: ClockTime = "07:00"
    max_hours: Annotated[float, Field(gt=0, le=16)] = 10
    task_timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=14400)] = 3600
    check_timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=3600)] = 900
    minimum_task_seconds: Annotated[int, Field(strict=True, ge=0, le=7200)] = 900
    max_tasks: Annotated[int, Field(strict=True, ge=1, le=500)] = 40
    max_attempts: Annotated[int, Field(strict=True, ge=1, le=20)] = 3
    max_consecutive_failures: Annotated[int, Field(strict=True, ge=1, le=20)] = 3
    write_paths: Annotated[tuple[str, ...], Field(min_length=1)] = ("*",)
    protected_paths: tuple[str, ...] = DEFAULT_PROTECTED_PATHS
    allow_deletions: bool = True
    tick_roadmap: bool = True
    verification_commands: Annotated[
        tuple[Annotated[tuple[CommandArgument, ...], Field(min_length=1)], ...],
        Field(min_length=1, max_length=8),
    ]

    _resolve_paths = field_validator("repository", "state_directory", "codex_binary")(resolve_path)
    _valid_timezone = field_validator("timezone")(valid_timezone)

    @field_validator("sources", "maintenance_focuses")
    @classmethod
    def unique_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("sources and maintenance focuses must be unique")
        return value

    @field_validator("write_paths", "protected_paths")
    @classmethod
    def relative_patterns(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            path = PurePosixPath(value)
            if (
                not value
                or path.is_absolute()
                or ".." in path.parts
                or any(ord(char) < 32 for char in value)
            ):
                raise ValueError("path patterns must be relative and must not contain '..'")
        return values

    @field_validator("roadmap_file")
    @classmethod
    def relative_roadmap(cls, value: str | None) -> str | None:
        if value is not None:
            safe_relative_path(value)
        return value

    @model_validator(mode="after")
    def safe_job(self) -> "AutopilotJob":
        if len({agent.name for agent in self.agents}) != len(self.agents):
            raise ValueError("agent names must be unique")
        if self.state_directory.is_relative_to(self.repository):
            raise ValueError("autopilot state must be outside the selected repository")
        encoded = json.dumps(self.verification_commands)
        if redact(encoded) != encoded or "\\u0000" in encoded:
            raise ValueError("commands must not contain credentials or NUL")
        return self

    def tool_commands(self) -> tuple[tuple[str, ...], ...]:
        return self.verification_commands

    def lane_sources(self, agent: AutopilotAgent) -> tuple[str, ...]:
        return agent.sources or self.sources


def load_autopilot_job(path: Path) -> AutopilotJob:
    path = path.expanduser().resolve()
    return AutopilotJob.model_validate(load_yaml(path), context={"base_directory": path.parent})


def night_deadline(job: AutopilotJob, now: datetime) -> datetime:
    """The next local `stop_at` (wall clock), but never more than `max_hours` of elapsed time."""
    if now.tzinfo is None:
        raise ValueError("the schedule clock must be timezone-aware")
    local = now.astimezone(ZoneInfo(job.timezone))
    hour, minute = map(int, job.stop_at.split(":"))
    stop = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if stop <= local:
        stop = (stop + timedelta(days=1)).replace(hour=hour, minute=minute)
    # Compare in UTC: aware datetimes sharing a tzinfo are compared by wall time.
    return min(stop.astimezone(UTC), now.astimezone(UTC) + timedelta(hours=job.max_hours))


class AgentReport(Model):
    model_config = ConfigDict(extra="ignore", frozen=True, hide_input_in_errors=True)
    status: AgentStatus
    summary: str = ""


def parse_report(output: bytes) -> AgentReport | None:
    """Read the agent's last valid `AUTOPILOT_RESULT: {...}` line, if any."""
    text = output.decode("utf-8", errors="replace")
    for raw in reversed(_REPORT.findall(text)):
        try:
            return AgentReport.model_validate(load_unique_json(raw))
        except (ValueError, ValidationError, RecursionError):
            continue
    return None


def _clean_text(value: str, limit: int) -> str:
    value = "".join(char for char in value if char in "\n\t" or ord(char) >= 32)
    return redact(value).strip()[:limit]


def _one_line(value: str, limit: int) -> str:
    return " ".join(_clean_text(value, 4 * limit).split())[:limit].rstrip()


@dataclass(frozen=True)
class WorkItem:
    key: str
    source: str
    title: str
    commit_type: str
    task: str
    milestone: str = ""
    roadmap_item: RoadmapItem | None = None


def roadmap_work(item: RoadmapItem, milestone: Milestone, roadmap_file: str) -> WorkItem:
    lines = [f"Roadmap milestone: {item.milestone}", f"Roadmap item: {item.text}"]
    if item.parent:
        lines.append(f"Parent item: {item.parent}")
    if item.details:
        lines.append(f"Item details:\n{item.details}")
    lines.extend(
        [
            f"Milestone context from {roadmap_file} (read-only):",
            "<<<",
            milestone.section,
            ">>>",
            "Implement this item completely if it fits in one session, including the tests and "
            "documentation it requires. Otherwise make coherent, verifiable progress and report "
            "partial.",
        ]
    )
    return WorkItem(
        key=item.key,
        source="roadmap",
        title=item.text,
        commit_type="feat",
        task="\n".join(lines),
        milestone=item.milestone,
        roadmap_item=item,
    )


def maintenance_work(focus: str) -> WorkItem:
    commit_type, instructions = FOCUSES[focus]
    return WorkItem(
        key=f"maintenance:{focus}",
        source="maintenance",
        title=f"{focus} maintenance pass",
        commit_type=commit_type,
        task=(
            f"Maintenance focus: {focus}\n{instructions}\n"
            "Make at most one coherent improvement backed by evidence. If nothing deserves a "
            "change, make no changes and report no_change; never invent problems."
        ),
    )


def build_prompt(
    job: AutopilotJob, item: WorkItem, roadmap_file: str | None, earlier: dict[str, object] | None
) -> str:
    protected = [*job.protected_paths, *([roadmap_file] if roadmap_file else [])]
    history = ""
    if earlier and earlier.get("status") == "partial":
        history = (
            f"An earlier session made partial progress on this task (local branch "
            f"{earlier.get('branch')}, commit {earlier.get('commit')}). If that commit is in "
            "this branch's history, continue from it; otherwise inspect it read-only with git "
            "show and redo only what is still needed.\n\n"
        )
    deletions = (
        "You may delete files that your change makes obsolete."
        if job.allow_deletions
        else "Do not delete files."
    )
    return (
        "You are an autonomous coding agent working unattended overnight in this repository. "
        "The repository owner authorized this run; nobody can answer questions before morning.\n\n"
        f"{item.task}\n\n{history}"
        "Rules:\n"
        "- Read AGENTS.md, CLAUDE.md, CONTRIBUTING.md and README.md when present, and follow "
        "the repository's conventions.\n"
        "- Work only on this task. Keep the change focused and avoid unrelated rewrites.\n"
        "- Do not commit, push, merge, rebase, switch branches or rewrite history. The "
        "supervisor verifies your changes and commits them to a local review branch.\n"
        f"- Write only paths matching {json.dumps(job.write_paths)}. Never edit "
        f"{json.dumps(protected)}; the supervisor maintains the roadmap. {deletions}\n"
        "- Never weaken, skip or delete tests or checks to make them pass. Never write "
        "credentials or secrets.\n"
        "- Prefer the project's existing dependencies; add one only when the task cannot "
        "reasonably be done without it.\n"
        "- The supervisor runs these checks after you finish and rejects the change if any "
        f"fails: {json.dumps(job.verification_commands)}. Run them yourself first.\n"
        "- Report honestly. Do not claim checks passed or work is complete without evidence.\n\n"
        "Finish with a short account of your changes, then end with exactly one final line:\n"
        'AUTOPILOT_RESULT: {"status": "done|partial|blocked|no_change", "summary": "..."}\n'
        "Use done when the task is complete and verified, partial when useful progress remains "
        "incomplete, blocked when a human decision or unavailable resource is required (say "
        "which), and no_change when nothing useful should change.\n"
    )


def commit_message(
    item: WorkItem, report: AgentReport | None, agent: AutopilotAgent, *, tick_only: bool
) -> tuple[str, str]:
    title = _one_line(item.title, 200).rstrip(".")
    title = title[:1].lower() + title[1:]
    if tick_only:
        subject = f'docs(roadmap): mark "{title}" as done'
    else:
        subject = f"{item.commit_type}(autopilot): {title}"
    subject = subject[:72].rstrip()
    lines = [
        f"Source: {item.source}"
        + (f" — {_one_line(item.milestone, 120)}" if item.milestone else ""),
        f"Agent: {agent.name} ({agent.model})",
        f"Agent status: {report.status if report else 'unreported'}",
    ]
    if tick_only:
        lines.append("The agent reported the item as already implemented; verify before merging.")
    if report and report.summary:
        lines.extend(["", _clean_text(report.summary, MAX_SUMMARY_CHARACTERS)])
    return subject, "\n".join(lines)


class _Rejected(Exception):
    """A rejected cycle; its work is saved as a patch and removed from the worktree."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _Cancelled(Exception):
    """The night is closing; the lane stops and leaves its current work in place."""


def _safe_reason(error: BaseException) -> str:
    reason = str(error) if isinstance(error, ValueError) else ""
    return reason if _REASON.fullmatch(reason) else "local_operation_failed"


def _branch_tip(repository: Path, branch: str) -> str | None:
    return (
        git(
            repository,
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}^{{commit}}",
            allowed_returncodes=(0, 1),
        ).strip()
        or None
    )


def _is_ancestor(repository: Path, ancestor: str, descendant: str) -> bool:
    try:
        common = git(repository, "merge-base", ancestor, descendant, allowed_returncodes=(0, 1))
        full = git(repository, "rev-parse", "--verify", "--quiet", f"{ancestor}^{{commit}}")
    except ValueError:
        return False
    return bool(common.strip()) and common.strip() == full.strip()


def _write_private_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)


def _check_path(name: str) -> None:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or ".git" in path.parts
        or "\\" in name
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
    ):
        raise _Rejected("agent_changed_unsafe_path")
    if _SECRET_FILE.search(name) or path.suffix.lower() in _SECRET_SUFFIXES:
        raise _Rejected("agent_changed_credential_path")


def _matches(name: str, patterns: tuple[str, ...] | list[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def find_roadmap(job: AutopilotJob, commit: str) -> str | None:
    candidates = (job.roadmap_file,) if job.roadmap_file else ROADMAP_CANDIDATES
    for candidate in candidates:
        listed = git(job.repository, "ls-tree", "-z", "--name-only", commit, "--", candidate)
        if candidate in listed.split("\0"):
            return candidate
    return None


def load_progress(job: AutopilotJob) -> dict[str, Any]:
    path = job.state_directory / "progress.json"
    progress = read_record(path) if path.exists() else {}
    if (
        not isinstance(progress, dict)
        or not isinstance(progress.setdefault("items", {}), dict)
        or not isinstance(progress.setdefault("lanes", {}), dict)
        or not isinstance(progress.setdefault("next_focus", 0), int)
    ):
        raise ValueError("invalid_autopilot_progress")
    return progress


class _Planner:
    """Hand out distinct work to lanes, in source order, and record outcomes."""

    def __init__(
        self,
        night: "_Night",
        roadmap: list[WorkItem],
    ):
        self.night = night
        self.job = night.job
        self.roadmap = roadmap
        self.items: dict[str, dict[str, object]] = night.progress["items"]
        self.claimed: set[str] = set()
        self.closed: set[str] = set()
        self.owners: dict[str, str] = {}
        self.started = 0
        self.idle_maintenance = 0
        self.exhausted_reason = "no_work_left"

    def _available(self, key: str, lane: str) -> bool:
        if key in self.claimed or key in self.closed or self.owners.get(key, lane) != lane:
            return False
        record = self.items.get(key)
        if record is None:
            return True
        attempts = record.get("attempts", 0)
        return (
            record.get("status") != "done"
            and isinstance(attempts, int)
            and (attempts < self.job.max_attempts)
        )

    def _maintenance(self) -> WorkItem | None:
        focuses = self.job.maintenance_focuses
        if self.idle_maintenance >= len(focuses):
            return None
        start: int = self.night.progress["next_focus"]
        for offset in range(len(focuses)):
            index = (start + offset) % len(focuses)
            item = maintenance_work(focuses[index])
            if item.key not in self.claimed:
                self.night.progress["next_focus"] = (index + 1) % len(focuses)
                return item
        return None

    def claim(self, lane: "_Lane") -> WorkItem | None:
        with self.night.lock:
            if self.started >= self.job.max_tasks:
                self.exhausted_reason = "max_tasks_reached"
                return None
            for source in lane.sources:
                item: WorkItem | None = None
                if source == "roadmap":
                    item = next(
                        (work for work in self.roadmap if self._available(work.key, lane.name)),
                        None,
                    )
                elif source == "maintenance":
                    item = self._maintenance()
                if item is not None:
                    self.claimed.add(item.key)
                    self.started += 1
                    return item
            return None

    def earlier(self, item: WorkItem) -> dict[str, object] | None:
        with self.night.lock:
            record = self.items.get(item.key)
            return dict(record) if record else None

    def finish(
        self,
        lane: "_Lane",
        item: WorkItem,
        outcome: str,
        report: AgentReport | None,
        commit: str | None,
    ) -> None:
        with self.night.lock:
            self.claimed.discard(item.key)
            if item.source == "maintenance":
                self.idle_maintenance = 0 if outcome == "committed" else self.idle_maintenance + 1
                self.night.save_progress()
                return
            if outcome == "interrupted":
                return
            record = self.items.setdefault(item.key, {"attempts": 0})
            attempts = record.get("attempts", 0)
            attempts = attempts if isinstance(attempts, int) else 0
            record.update(
                title=_one_line(item.title, 200),
                source=item.source,
                last_outcome=outcome,
                updated_at=utc_now().isoformat(),
            )
            if outcome == "committed" and report is not None and report.status == "done":
                record.update(status="done", branch=lane.branch, commit=commit)
                self.closed.add(item.key)
            elif outcome == "committed":
                record.update(status="partial", branch=lane.branch, commit=commit)
                record["attempts"] = attempts + 1
                self.owners[item.key] = lane.name
            else:
                if outcome not in ("agent_failed", "agent_unavailable"):
                    record["attempts"] = attempts + 1
                status = report.status if report and report.status == "blocked" else "open"
                record["status"] = status if outcome == "no_change" else "failed"
                self.closed.add(item.key)
            self.night.save_progress()


class _CycleState(TypedDict):
    cycles: int
    outcome: str


class _Lane:
    def __init__(self, night: "_Night", agent: AutopilotAgent):
        self.night, self.job, self.agent = night, night.job, agent
        self.name = agent.name
        self.sources = self.job.lane_sources(agent)
        self.directory = night.directory / agent.name
        self.root = self.directory / "worktree"
        self.branch = (
            f"token_maxxxer/autopilot-{self.job.name}-{agent.name}-{night.date.replace('-', '')}"
        )
        self.record: dict[str, object] = {
            "agent": agent.name,
            "model": agent.model,
            "sources": list(self.sources),
            "branch": self.branch,
            "worktree": str(self.root),
            "status": "pending",
            "reason": "",
            "base_commit": None,
            "continued_from": None,
            "commits": [],
        }
        self.failures = 0
        self.item: WorkItem | None = None
        self.cycle: dict[str, object] = {}
        self.report: AgentReport | None = None
        self.changed: list[str] = []
        self.thread: threading.Thread | None = None
        self.finished = threading.Event()

    # Preparation runs in the main thread, so worktree creation is serialized.
    def prepare(self, source_head: str) -> None:
        repository = self.job.repository
        base, continued = source_head, None
        previous = self.night.progress["lanes"].get(self.name)
        if isinstance(previous, dict) and isinstance(previous.get("branch"), str):
            tip = _branch_tip(repository, previous["branch"])
            if tip and tip != source_head and _is_ancestor(repository, source_head, tip):
                base, continued = tip, previous["branch"]
        if _branch_tip(repository, self.branch):
            raise ValueError("autopilot_branch_exists")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        git(
            repository,
            "worktree",
            "add",
            "-q",
            "-b",
            self.branch,
            str(self.root),
            base,
            timeout=120,
        )
        self.night.update(self.record, base_commit=base, continued_from=continued, status="ready")

    def run(self) -> None:
        try:
            self._run()
        finally:
            self.finished.set()

    def _run(self) -> None:
        try:
            self.night.update(self.record, status="baseline")
            checks = self.run_checks()
            self.night.update(self.record, baseline=checks)
            if not all(check["passed"] for check in checks):
                raise _Rejected("baseline_failed")
            if git(self.root, "status", "--porcelain=v1", "-z"):
                raise _Rejected("baseline_changed_worktree")
            self.night.update(self.record, status="running")
            graph = StateGraph(_CycleState)
            graph.add_node("select", self.select)
            graph.add_node("execute", self.execute)
            graph.add_node("verify", self.verify)
            graph.add_node("record", self.record_result)
            graph.add_edge(START, "select")
            graph.add_conditional_edges(
                "select", lambda state: "execute" if state["outcome"] == "selected" else END
            )
            graph.add_edge("execute", "verify")
            graph.add_edge("verify", "record")
            graph.add_edge("record", "select")
            graph.compile().invoke(
                {"cycles": 0, "outcome": ""}, {"recursion_limit": 4 * self.job.max_tasks + 10}
            )
        except _Cancelled:
            self.abandon("interrupted")
            self.night.update(self.record, status="stopped", reason=self.night.stop_reason)
        except _Rejected as rejection:
            self.night.update(self.record, status="failed", reason=rejection.code)
        except Exception as error:
            reason = _safe_reason(error)
            self.abandon("failed")
            self.night.update(
                self.record, status="failed", reason=reason, exception=type(error).__name__
            )

    def abandon(self, outcome: str) -> None:
        if self.item is not None:
            self.night.planner.finish(self, self.item, "interrupted", None, None)
            self.night.update(self.cycle, outcome=outcome, finished_at=utc_now().isoformat())
            self.item = None

    def remaining(self) -> float:
        remaining = self.night.remaining()
        if remaining <= 0 or self.night.cancel.is_set():
            raise _Cancelled
        return remaining

    def agent_timeout(self) -> float:
        return min(
            float(self.job.task_timeout_seconds),
            self.night.remaining() - self.job.check_timeout_seconds,
        )

    def run_checks(self) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for command in self.job.verification_commands:
            result = run_command(
                command,
                self.root,
                min(float(self.job.check_timeout_seconds), self.remaining()),
                self.night.environment,
                max_output_bytes=65_536,
                combine_stderr=True,
                cancel=self.night.cancel,
            )
            if result.cancelled:
                raise _Cancelled
            passed = result.exit_code == 0 and not result.timed_out
            entry: dict[str, object] = {
                "command": list(command),
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "passed": passed,
            }
            if not passed:
                output = redact(result.output.decode("utf-8", errors="replace"))
                entry["output_tail"] = output[-4000:]
            results.append(entry)
            if not passed:
                break
        return results

    def stop(self, state: _CycleState, reason: str) -> _CycleState:
        self.night.update(self.record, status="finished", reason=reason)
        return {"cycles": state["cycles"], "outcome": "stopped"}

    def select(self, state: _CycleState) -> _CycleState:
        self.remaining()
        if self.failures >= self.job.max_consecutive_failures:
            return self.stop(state, "too_many_failures")
        if self.night.remaining() < self.job.minimum_task_seconds or self.agent_timeout() <= 0:
            return self.stop(state, "window_closing")
        item = self.night.planner.claim(self)
        if item is None:
            return self.stop(state, self.night.planner.exhausted_reason)
        self.item, self.report, self.changed = item, None, []
        self.cycle = self.night.open_cycle(self, item, git(self.root, "rev-parse", "HEAD").strip())
        return {"cycles": state["cycles"] + 1, "outcome": "selected"}

    def execute(self, state: _CycleState) -> _CycleState:
        assert self.item is not None
        prompt = build_prompt(
            self.job, self.item, self.night.roadmap_file, self.night.planner.earlier(self.item)
        )
        result = run_command(
            codex_exec_command(self.job.codex_binary, self.agent.model),
            self.root,
            max(1.0, self.agent_timeout()),
            self.night.environment,
            max_output_bytes=MAX_AGENT_OUTPUT_BYTES,
            input_bytes=prompt.encode("utf-8"),
            cancel=self.night.cancel,
        )
        if result.cancelled:
            raise _Cancelled
        if result.exit_code is None:
            outcome = "agent_unavailable"
        elif result.timed_out:
            outcome = "agent_timeout"
        elif result.exit_code != 0:
            outcome = "agent_failed"
        else:
            outcome = "agent_completed"
        self.report = parse_report(result.output)
        self.night.update(
            self.cycle,
            agent_outcome=outcome,
            agent_status=self.report.status if self.report else None,
            summary=_clean_text(self.report.summary, MAX_SUMMARY_CHARACTERS)
            if self.report
            else None,
        )
        return {"cycles": state["cycles"], "outcome": outcome}

    def staged_entries(self) -> list[tuple[str, str, str]]:
        raw = git(
            self.root, "diff", "--cached", "--raw", "-z", "--no-renames", "--no-abbrev", "HEAD"
        )
        parts = raw.split("\0")
        entries = []
        for header, name in zip(parts[0::2], parts[1::2], strict=False):
            if not header:
                break
            fields = header.lstrip(":").split()
            entries.append((fields[4][:1], fields[1], name))
        return entries

    def tick(self, item: RoadmapItem) -> bool:
        roadmap = self.night.roadmap_file
        if roadmap is None:
            return False
        path = self.root / roadmap
        if path.is_symlink() or not path.is_file():
            self.night.update(self.cycle, roadmap_tick="roadmap_changed")
            return False
        with path.open(encoding="utf-8", newline="") as stream:
            content = stream.read()
        updated = mark_done(content, item)
        if updated is None:
            self.night.update(self.cycle, roadmap_tick="roadmap_changed")
            return False
        with path.open("w", encoding="utf-8", newline="") as stream:
            stream.write(updated)
        git(self.root, "add", "--", roadmap)
        self.night.update(self.cycle, roadmap_tick="checked")
        return True

    def check_changes(self) -> str:
        assert self.item is not None
        if git(self.root, "branch", "--show-current").strip() != self.branch:
            raise ValueError("agent_changed_branch")
        if git(self.root, "rev-parse", "HEAD").strip() != self.cycle["base_commit"]:
            raise _Rejected("agent_changed_head")
        git(self.root, "add", "-A")
        entries = self.staged_entries()
        protected = [*self.job.protected_paths]
        if self.night.roadmap_file:
            protected.append(self.night.roadmap_file)
        for status, mode, name in entries:
            _check_path(name)
            if _matches(name, protected):
                raise _Rejected("agent_changed_protected_path")
            if not _matches(name, self.job.write_paths):
                raise _Rejected("agent_changed_unapproved_path")
            if status == "D":
                if not self.job.allow_deletions:
                    raise _Rejected("agent_removed_files")
                continue
            if mode not in ("100644", "100755"):
                raise _Rejected("agent_changed_file_mode")
            if (self.root / name).stat().st_size > MAX_CHANGED_FILE_BYTES:
                raise _Rejected("agent_wrote_large_file")
        self.changed = sorted(name for _, _, name in entries)
        ticked = False
        roadmap_item = self.item.roadmap_item
        if (
            roadmap_item is not None
            and self.job.tick_roadmap
            and self.report is not None
            and self.report.status == "done"
        ):
            ticked = self.tick(roadmap_item)
        if not entries and not ticked:
            return "no_change"
        try:
            diff = git(self.root, "diff", "--cached", "-U0", "--no-color", "--no-ext-diff", "HEAD")
        except ValueError:
            raise _Rejected("unreadable_change") from None
        if any(
            line.startswith("+") and not line.startswith("+++") and _SECRET_VALUE.search(line)
            for line in diff.splitlines()
        ):
            raise _Rejected("credential_in_change")
        checks = self.run_checks()
        self.night.update(self.cycle, changed_files=self.changed, checks=checks)
        if not all(check["passed"] for check in checks):
            raise _Rejected("verification_failed")
        if git(self.root, "diff", "--name-only", "-z") or git(
            self.root, "ls-files", "--others", "--exclude-standard", "-z"
        ):
            raise _Rejected("verification_changed_worktree")
        return "verified"

    def discard(self) -> None:
        base = str(self.cycle["base_commit"])
        git(self.root, "add", "-A")
        patch = git_output(self.root, "diff", "--cached", "--binary", base, timeout=60)
        if patch:
            path = self.directory / f"cycle-{self.cycle['index']:03d}.patch"
            _write_private_bytes(path, patch)
            self.night.update(self.cycle, patch=str(path))
        git(self.root, "reset", "-q", "--hard", base, timeout=60)
        git(self.root, "clean", "-fdq", timeout=60)

    def verify(self, state: _CycleState) -> _CycleState:
        outcome = state["outcome"]
        if outcome in ("agent_failed", "agent_unavailable"):
            self.discard()
            return {"cycles": state["cycles"], "outcome": outcome}
        try:
            outcome = self.check_changes()
        except _Rejected as rejection:
            outcome = rejection.code
            self.discard()
        return {"cycles": state["cycles"], "outcome": outcome}

    def commit(self) -> str:
        assert self.item is not None
        subject, body = commit_message(
            self.item, self.report, self.agent, tick_only=not self.changed
        )
        with self.night.git_lock:
            git(
                self.root,
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-q",
                "-m",
                subject,
                "-m",
                body,
                timeout=120,
            )
        commit = git(self.root, "rev-parse", "HEAD").strip()
        commits = self.record["commits"]
        assert isinstance(commits, list)
        self.night.update(self.record, commits=[*commits, commit])
        return commit

    def record_result(self, state: _CycleState) -> _CycleState:
        assert self.item is not None
        outcome, commit = state["outcome"], None
        if outcome == "verified":
            commit = self.commit()
            outcome = "committed"
        if outcome in ("committed", "no_change"):
            self.failures = 0
        else:
            self.failures += 1
        self.night.planner.finish(self, self.item, outcome, self.report, commit)
        self.night.update(
            self.cycle, outcome=outcome, commit=commit, finished_at=utc_now().isoformat()
        )
        self.item = None
        return {"cycles": state["cycles"], "outcome": outcome}

    def finalize(self) -> None:
        if not self.root.exists():
            return
        repository = self.job.repository
        try:
            head = git(self.root, "rev-parse", "HEAD").strip()
            base = str(self.record["base_commit"])
            count = int(git(self.root, "rev-list", "--count", f"{base}..{head}").strip())
            self.night.update(self.record, head=head, new_commits=count)
            if git(self.root, "status", "--porcelain=v1", "-z"):
                self.night.update(self.record, worktree_retained=True)
                return
            git(repository, "worktree", "remove", str(self.root), timeout=120)
            if count:
                self.night.progress["lanes"][self.name] = {"branch": self.branch, "commit": head}
            else:
                git(repository, "branch", "-D", self.branch)
                self.night.update(self.record, branch_removed=True)
        except ValueError:
            self.night.update(self.record, cleanup="failed", worktree_retained=True)


class _Night:
    def __init__(self, job: AutopilotJob, date: str, now: datetime):
        self.job, self.date = job, date
        self.directory = job.state_directory / "runs" / date
        self.lock = threading.RLock()
        self.git_lock = threading.Lock()
        self.cancel = threading.Event()
        self.stop_reason = "deadline_reached"
        deadline = night_deadline(job, now)
        elapsed = (deadline - now.astimezone(UTC)).total_seconds()
        self.deadline = time.monotonic() + max(0.0, elapsed)
        self.environment = runtime_environment()
        self.environment.update(GIT_TERMINAL_PROMPT="0", LANGSMITH_TRACING="false")
        self.progress: dict[str, Any] = {"items": {}, "lanes": {}, "next_focus": 0}
        self.roadmap_file: str | None = None
        self.lanes: list[_Lane] = []
        self.cycles: list[dict[str, object]] = []
        self.planner = _Planner(self, [])
        self.record: dict[str, object] = {
            "date": date,
            "job": job.name,
            "status": "starting",
            "reason": "",
            "started_at": utc_now().isoformat(),
            "deadline": deadline.astimezone(ZoneInfo(job.timezone)).isoformat(),
        }

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def update(self, target: dict[str, object], **fields: object) -> None:
        with self.lock:
            target.update(fields)
            self.save()

    def save(self) -> None:
        with self.lock:
            self.record["lanes"] = [lane.record for lane in self.lanes]
            self.record["cycles"] = self.cycles
            write_record(self.directory / "night.json", self.record)
            write_private_text(self.directory / "report.md", night_report(self.record))

    def save_progress(self) -> None:
        with self.lock:
            write_record(self.job.state_directory / "progress.json", self.progress)

    def open_cycle(self, lane: _Lane, item: WorkItem, base: str) -> dict[str, object]:
        with self.lock:
            cycle: dict[str, object] = {
                "index": len(self.cycles) + 1,
                "agent": lane.name,
                "source": item.source,
                "key": item.key,
                "title": _one_line(item.title, 200),
                "milestone": _one_line(item.milestone, 200),
                "outcome": "running",
                "base_commit": base,
                "started_at": utc_now().isoformat(),
            }
            self.cycles.append(cycle)
            self.save()
            return cycle

    def reconcile(self, source_head: str) -> None:
        """Reopen items whose recorded work was neither merged nor kept on a branch."""
        for record in self.progress["items"].values():
            if not isinstance(record, dict) or record.get("status") != "done":
                continue
            commit, branch = record.get("commit"), record.get("branch")
            if not isinstance(commit, str):
                record["status"] = "open"
                continue
            merged = _is_ancestor(self.job.repository, commit, source_head)
            tip = _branch_tip(self.job.repository, branch) if isinstance(branch, str) else None
            if not merged and not (tip and _is_ancestor(self.job.repository, commit, tip)):
                record["status"] = "open"

    def roadmap_items(self, source_head: str) -> list[WorkItem]:
        if not any("roadmap" in self.job.lane_sources(agent) for agent in self.job.agents):
            return []
        self.roadmap_file = find_roadmap(self.job, source_head)
        if self.roadmap_file is None:
            self.record["roadmap"] = {"status": "not_found"}
            return []
        try:
            milestones = parse_roadmap(
                git(self.job.repository, "show", f"{source_head}:{self.roadmap_file}")
            )
        except ValueError:
            self.record["roadmap"] = {"status": "invalid", "file": self.roadmap_file}
            self.roadmap_file = None
            return []
        work = [
            roadmap_work(item, milestone, self.roadmap_file)
            for milestone in milestones
            for item in milestone.items
            if item.ready
        ]
        self.record["roadmap"] = {
            "status": "loaded",
            "file": self.roadmap_file,
            "milestones": len(milestones),
            "open_items": sum(len(milestone.open_items) for milestone in milestones),
            "ready_items": len(work),
        }
        return work

    def prepare(self) -> None:
        job = self.job
        repository_root(job.repository)
        if not job.codex_binary.is_file() or not os.access(job.codex_binary, os.X_OK):
            raise ValueError("codex_binary_unavailable")
        git(job.repository, "var", "GIT_AUTHOR_IDENT")
        git(job.repository, "var", "GIT_COMMITTER_IDENT")
        source_head = git(job.repository, "rev-parse", "HEAD").strip()
        self.record["source_commit"] = source_head
        self.progress = load_progress(job)
        self.reconcile(source_head)
        self.planner = _Planner(self, self.roadmap_items(source_head))
        self.lanes = [_Lane(self, agent) for agent in job.agents]
        self.update(self.record, status="preparing")
        for lane in self.lanes:
            lane.prepare(source_head)

    def stop_lanes(self, reason: str) -> None:
        self.stop_reason = reason
        self.cancel.set()
        for lane in self.lanes:
            if lane.thread is not None:
                lane.finished.wait()

    def wait_for_lanes(self) -> None:
        # A signal interrupting Thread.join can mark a still-running thread as stopped
        # (bpo-45274), so lanes report their own completion through an event.
        while not all(lane.finished.is_set() for lane in self.lanes if lane.thread):
            time.sleep(0.1)

    def run(self) -> dict[str, object]:
        self.save()
        try:
            with _signals(max(0.001, self.remaining())):
                self.prepare()
                self.update(self.record, status="running")
                for lane in self.lanes:
                    lane.thread = threading.Thread(
                        target=lane.run, name=f"autopilot-{lane.name}", daemon=True
                    )
                    lane.thread.start()
                self.wait_for_lanes()
            failed = all(lane.record["status"] == "failed" for lane in self.lanes)
            status, reason = ("failed", "all_agents_failed") if failed else ("completed", "")
        except _DeadlineReached:
            self.stop_lanes("deadline_reached")
            status, reason = "completed", "deadline_reached"
        except KeyboardInterrupt:
            self.stop_lanes("interrupted_by_signal")
            status, reason = "interrupted", "interrupted_by_signal"
        except Exception as error:
            self.stop_lanes("night_failed")
            status, reason = "failed", _safe_reason(error)
            self.record["exception"] = type(error).__name__
        for lane in self.lanes:
            lane.finalize()
        if not reason:
            reasons = {str(lane.record["reason"]) for lane in self.lanes}
            reason = reasons.pop() if len(reasons) == 1 else "agents_finished"
        self.save_progress()
        self.update(self.record, status=status, reason=reason, finished_at=utc_now().isoformat())
        return self.record


def _cell(value: object) -> str:
    return _one_line(str(value or ""), 120).replace("|", "\\|")


def night_report(record: dict[str, object]) -> str:
    lanes = record.get("lanes") or []
    cycles = record.get("cycles") or []
    assert isinstance(lanes, list) and isinstance(cycles, list)
    roadmap = record.get("roadmap")
    lines = [
        f"# Autopilot night — {record.get('job')} — {record.get('date')}",
        "",
        f"- Status: {record.get('status')}"
        + (f" ({record['reason']})" if record.get("reason") else ""),
        f"- Started: {record.get('started_at')}; deadline: {record.get('deadline')}",
        f"- Finished: {record.get('finished_at') or 'running'}",
        f"- Source commit: {record.get('source_commit', 'unknown')}",
    ]
    if isinstance(roadmap, dict):
        lines.append(
            f"- Roadmap: {roadmap.get('file', 'none')} — {roadmap.get('status')}"
            + (
                f", {roadmap.get('ready_items')} ready of {roadmap.get('open_items')} open items"
                if roadmap.get("status") == "loaded"
                else ""
            )
        )
    lines.extend(["", "## Agents", "", "| Agent | Model | Branch | Commits | Status |"])
    lines.append("| --- | --- | --- | --- | --- |")
    for lane in lanes:
        commits = lane.get("commits") or []
        status = f"{lane.get('status')} {lane.get('reason') or ''}".strip()
        branch = "removed (no commits)" if lane.get("branch_removed") else lane.get("branch")
        lines.append(
            f"| {_cell(lane.get('agent'))} | {_cell(lane.get('model'))} | `{_cell(branch)}` "
            f"| {len(commits) if isinstance(commits, list) else 0} | {_cell(status)} |"
        )
    lines.extend(["", "## Cycles", ""])
    if cycles:
        lines.extend(["| # | Agent | Source | Task | Outcome | Commit |"])
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for cycle in cycles:
            commit = str(cycle.get("commit") or "")[:12]
            lines.append(
                f"| {cycle.get('index')} | {_cell(cycle.get('agent'))} "
                f"| {_cell(cycle.get('source'))} | {_cell(cycle.get('title'))} "
                f"| {_cell(cycle.get('outcome'))} | {commit} |"
            )
    else:
        lines.append("No cycle started.")
    attention = [
        f"- Cycle {cycle.get('index')} ({cycle.get('agent')}): {cycle.get('outcome')}; "
        f"patch `{cycle['patch']}`"
        for cycle in cycles
        if cycle.get("patch")
    ]
    attention.extend(
        f"- Worktree retained for inspection: `{lane.get('worktree')}`"
        for lane in lanes
        if lane.get("worktree_retained")
    )
    if attention:
        lines.extend(["", "## Needs attention", "", *attention])
    lines.extend(
        [
            "",
            "Review each branch and its checks before merging. Nothing was pushed or merged.",
            "",
        ]
    )
    return "\n".join(lines)


def preview_autopilot(job: AutopilotJob, date: str, now: datetime) -> dict[str, object]:
    """Describe the next night without writes, model access or network requests."""
    repository_root(job.repository)
    head = git(job.repository, "rev-parse", "HEAD").strip()
    path = job.state_directory / "progress.json"
    progress = load_progress(job) if path.exists() else {"items": {}}
    items = progress["items"]
    assert isinstance(items, dict)
    roadmap = find_roadmap(job, head)
    upcoming: list[dict[str, str]] = []
    if roadmap:
        for item in ready_items(parse_roadmap(git(job.repository, "show", f"{head}:{roadmap}"))):
            record = items.get(item.key)
            if isinstance(record, dict) and (
                record.get("status") == "done"
                or int(str(record.get("attempts", 0))) >= job.max_attempts
            ):
                continue
            upcoming.append({"key": item.key, "milestone": item.milestone, "item": item.text})
    return {
        "status": "preview",
        "date": date,
        "deadline": night_deadline(job, now).astimezone(ZoneInfo(job.timezone)).isoformat(),
        "source_commit": head,
        "agents": [
            {"name": agent.name, "model": agent.model, "sources": list(job.lane_sources(agent))}
            for agent in job.agents
        ],
        "roadmap_file": roadmap,
        "next_roadmap_items": upcoming[:20],
        "remaining_roadmap_items": len(upcoming),
        "maintenance_focuses": list(job.maintenance_focuses),
        "verification_commands": [list(command) for command in job.verification_commands],
    }


def run_autopilot(
    job: AutopilotJob,
    *,
    scheduled: bool = False,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    now = now or utc_now()
    date = run_date(job, now, scheduled=scheduled)
    if date is None:
        return {"status": "skipped", "reason": "outside_start_window"}
    if dry_run:
        return preview_autopilot(job, date, now)
    directory = job.state_directory / "runs" / date
    if (directory / "attempted").exists():
        return {"status": "skipped", "reason": "already_attempted", "date": date}
    with _repository_lock(repository_root(job.repository)):
        if not claim_attempt(directory):
            return {"status": "skipped", "reason": "already_attempted", "date": date}
        return _Night(job, date, now).run()
