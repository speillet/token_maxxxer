"""Repository/skill pickers and explicit overnight-session commands."""

import argparse
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Literal

from token_maxxxer.config import Config, ProviderConfig, load_config
from token_maxxxer.credentials import resolve_credential
from token_maxxxer.local_state import default_state_directory, read_record, write_record
from token_maxxxer.models import Model
from token_maxxxer.night import (
    NightPlan,
    NightSession,
    list_sessions,
    load_session,
    public_session_json,
    run_night,
)
from token_maxxxer.providers import create_provider
from token_maxxxer.redaction import redact
from token_maxxxer.repositories import (
    git,
    load_history,
    local_path,
    remember_repository,
    repository_root,
    repository_suggestions,
)
from token_maxxxer.skills import Skill, discover_skills, select_skill


class _Profile(Model):
    provider: ProviderConfig
    env_file: Path


def add_commands(
    parser: argparse.ArgumentParser,
    commands: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    parser.add_argument("--state-dir", type=Path, help="private history and session directory")
    repositories = commands.add_parser("repos", help="list local repositories and recent paths")
    repositories.add_argument("--root", type=Path, action="append", default=[])
    repositories.add_argument("--json", action="store_true")
    skills = commands.add_parser("skills", help="list repository, user and built-in skills")
    skills.add_argument("--repo", type=Path, default=Path.cwd())
    skills.add_argument("--json", action="store_true")
    sessions = commands.add_parser("sessions", help="inspect saved overnight sessions")
    sessions.add_argument("id", nargs="?")
    sessions.add_argument("--json", action="store_true")
    night = commands.add_parser("night", help="repeat a skill in an isolated worktree")
    night.add_argument("repository", nargs="?", help="local repository path or file:// URL")
    night.add_argument("--skill", default="auto", help="skill ID, name, SKILL.md path, or auto")
    night.add_argument("--mode", choices=("edit", "review"), default="edit")
    night.add_argument("--hours", type=float, default=8)
    night.add_argument("--max-calls", type=int, default=100)
    night.add_argument("--interval", type=float, default=60, help="seconds between skill cycles")
    night.add_argument("--provider", choices=("claude", "openai", "copilot"))
    night.add_argument("--model", help="explicit provider model ID")
    night.add_argument("--env-file", type=Path, help="private credential-reference file")
    night.add_argument(
        "--verify",
        action="append",
        default=[],
        help="approved verification command; quote arguments, no shell is used",
    )
    night.add_argument("--verification-timeout", type=float, default=300)
    night.add_argument("--dry-run", action="store_true", help="preview without files or API access")
    night.add_argument(
        "--yes", action="store_true", help="start without an interactive confirmation"
    )
    night.add_argument("--json", action="store_true")


def _display(value: str | Path) -> str:
    return "".join(char if char.isprintable() else "?" for char in redact(str(value)))


def _input(prompt: str, default: str = "") -> str:
    try:
        answer = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    except EOFError as exc:
        raise ValueError(
            "input ended; use explicit night arguments and --yes for unattended runs"
        ) from exc
    return answer or default


def _configuration(arguments: argparse.Namespace) -> Config | None:
    path = arguments.config or Path("token_maxxxer.yaml")
    return load_config(path) if arguments.config or path.is_file() else None


def _repositories(arguments: argparse.Namespace, config: Config | None, state: Path) -> list[Path]:
    roots = tuple(getattr(arguments, "root", []) or [Path.cwd().parent])
    return repository_suggestions(
        roots, config.repositories.allowed if config else (), load_history(state)
    )


def _pick_repository(paths: list[Path], state: Path) -> Path:
    recent = {entry.path for entry in load_history(state).repositories}
    print("Local repositories (recent selections first):")
    for index, path in enumerate(paths, 1):
        print(f"  {index}. {_display(path)}{' [recent]' if path in recent else ''}")
    value = _input("Repository number or another local path", "1" if paths else "")
    if value.isdecimal() and 1 <= int(value) <= len(paths):
        return paths[int(value) - 1]
    if not value:
        raise ValueError("a local repository is required")
    return repository_root(local_path(value))


def _pick_skill(skills: list[Skill], suggested: Skill) -> Skill:
    print("Available skills:")
    for index, skill in enumerate(skills, 1):
        marker = " [suggested]" if skill.id == suggested.id else ""
        print(f"  {index}. {_display(skill.id)}{marker}: {_display(skill.description)}")
    default = str(next(index for index, skill in enumerate(skills, 1) if skill.id == suggested.id))
    selector = _input("Skill number, ID or SKILL.md path", default)
    if selector.isdecimal() and 1 <= int(selector) <= len(skills):
        return skills[int(selector) - 1]
    return select_skill(skills, selector, mode="edit")


def execute(arguments: argparse.Namespace) -> int:
    state = (arguments.state_dir or default_state_directory()).expanduser().resolve()
    command = arguments.command
    if command == "sessions":
        if arguments.id:
            if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}", arguments.id):
                raise ValueError("invalid session ID")
            session = load_session(state / "runs" / arguments.id)
            if arguments.json:
                print(public_session_json(session))
            else:
                report = state / "runs" / arguments.id / "report.md"
                text = (
                    report.read_text(encoding="utf-8")
                    if report.is_file()
                    else f"Session {session.id}: {session.state}; calls={session.calls}"
                )
                print("\n".join(_display(line) for line in text.splitlines()))
                if session.state in ("preparing", "running"):
                    print(
                        "This record may be active or interrupted; "
                        "it will not be replayed automatically."
                    )
        else:
            sessions = list_sessions(state)
            if arguments.json:
                print(
                    json.dumps([json.loads(public_session_json(session)) for session in sessions])
                )
            else:
                for session in sessions:
                    print(f"{session.id}\t{session.state}\t{_display(session.plan.repository)}")
                if not sessions:
                    print("No saved sessions.")
        return 0
    config = _configuration(arguments)
    if command == "repos":
        paths = _repositories(arguments, config, state)
        print(
            json.dumps([str(path) for path in paths])
            if arguments.json
            else "\n".join(_display(path) for path in paths) or "No local repositories found."
        )
        return 0
    if command == "skills":
        skills = discover_skills(repository_root(arguments.repo))
        print(
            json.dumps(
                [
                    {
                        "id": skill.id,
                        "description": skill.description,
                        "path": str(skill.path) if skill.path else None,
                    }
                    for skill in skills
                ]
            )
            if arguments.json
            else "\n".join(f"{_display(s.id)}\t{_display(s.description)}" for s in skills)
        )
        return 0
    return _night(arguments, config, state)


def _night(arguments: argparse.Namespace, config: Config | None, state: Path) -> int:
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    wizard = arguments.command is None
    if wizard and not interactive:
        raise ValueError(
            "interactive selection requires a terminal; use night PATH --model MODEL --yes"
        )
    repository_argument = getattr(arguments, "repository", None)
    if repository_argument:
        repository = repository_root(local_path(repository_argument))
    elif interactive:
        repository = _pick_repository(_repositories(arguments, config, state), state)
    else:
        raise ValueError("pass a local repository path for unattended execution")
    mode: Literal["edit", "review"] = (
        "review" if getattr(arguments, "mode", "edit") == "review" else "edit"
    )
    skills = discover_skills(repository)
    suggested = select_skill(skills, getattr(arguments, "skill", "auto"), mode=mode)
    if wizard:
        previous = next(
            (entry.skill for entry in load_history(state).repositories if entry.path == repository),
            None,
        )
        if previous and any(skill.id == previous for skill in skills):
            suggested = select_skill(skills, previous, mode=mode)
        skill = _pick_skill(skills, suggested)
    else:
        skill = suggested
    profile_path = state / "profile.json"
    profile = (
        _Profile.model_validate(read_record(profile_path))
        if config is None and profile_path.exists()
        else None
    )
    settings = config.provider if config else profile.provider if profile else None
    provider_name = getattr(arguments, "provider", None) or (settings.name if settings else None)
    model = getattr(arguments, "model", None)
    if model is None and settings and provider_name == settings.name:
        model = settings.model
    if provider_name is None:
        if not interactive:
            raise ValueError("configure a provider/model or pass --provider and --model")
        provider_name = _input("Provider (claude or openai)", "claude")
    if not model:
        if not interactive:
            raise ValueError("an explicit --model or configured model is required")
        model = _input("Model ID from your provider account")
    values = settings.model_dump() if settings else {}
    settings = ProviderConfig.model_validate({**values, "name": provider_name, "model": model})
    env_file = getattr(arguments, "env_file", None)
    env_file = (
        (
            env_file
            or (config.authentication.env_file if config else None)
            or (profile.env_file if profile else None)
            or Path(".env")
        )
        .expanduser()
        .resolve()
    )
    hours = getattr(arguments, "hours", 8)
    max_calls = getattr(arguments, "max_calls", 100)
    verification = [shlex.split(value) for value in getattr(arguments, "verify", [])]
    if wizard:
        hours = float(_input("Maximum duration in hours", "8"))
        max_calls = int(_input("Maximum API calls", "100"))
        check = _input("Optional verification command (no shell operators)")
        if check:
            verification.append(shlex.split(check))
    if len(verification) > 5 or any("\x00" in arg for command in verification for arg in command):
        raise ValueError("use at most five verification commands without NUL characters")
    plan = NightPlan(
        repository=repository,
        skill=skill.id,
        mode=mode,
        provider=settings,
        hours=hours,
        max_calls=max_calls,
        interval_seconds=getattr(arguments, "interval", 60),
        verification_commands=tuple(tuple(command) for command in verification),
        verification_timeout_seconds=getattr(arguments, "verification_timeout", 300),
    )
    if state.is_relative_to(repository):
        raise ValueError("--state-dir must be outside the selected repository")
    if mode == "review" and verification:
        raise ValueError("review mode does not execute verification commands")
    json_output = getattr(arguments, "json", False)
    if getattr(arguments, "dry_run", False):
        print(
            json.dumps({"dry_run": True, "plan": plan.model_dump(mode="json")})
            if json_output
            else _plan_text(plan)
        )
        return 0
    if not json_output:
        print(_plan_text(plan))
    if not getattr(arguments, "yes", False):
        if not interactive:
            raise ValueError("execution needs --yes outside a terminal; use --dry-run to preview")
        if (
            _input("Start this session and use the selected API allocation? (yes/no)", "no").lower()
            != "yes"
        ):
            print("Session cancelled. Nothing was launched.")
            return 0
    if mode == "edit" and git(repository, "status", "--porcelain=v1", "-z"):
        raise ValueError(
            "edit mode requires a clean repository; commit or save existing work first"
        )
    provider = create_provider(settings)
    credential = resolve_credential(settings, env_file)
    remember_repository(state, repository, skill.id)
    write_record(
        profile_path, _Profile(provider=settings, env_file=env_file).model_dump(mode="json")
    )

    def progress(current: NightSession) -> None:
        print(
            f"Session {current.id}: {current.calls}/{plan.max_calls} API calls",
            file=sys.stderr,
            flush=True,
        )

    session = run_night(plan, skill, state, provider, credential, progress=progress)
    if json_output:
        print(public_session_json(session))
    else:
        print(f"Session {session.id}: {session.state} ({session.reason})")
        print(f"Report: {state / 'runs' / session.id / 'report.md'}")
        if session.worktree:
            print(f"Inspect changes: git -C {shlex.quote(str(session.worktree))} diff")
    return 130 if session.state == "interrupted" else 1 if session.state == "failed" else 0


def _plan_text(plan: NightPlan) -> str:
    return (
        f"Repository: {_display(plan.repository)}\nSkill: {_display(plan.skill)}\n"
        f"Provider: {plan.provider.name} / {_display(plan.provider.model)}\n"
        f"Mode: {plan.mode}; maximum {plan.hours:g} hours, {plan.max_calls} API calls; "
        f"{plan.interval_seconds:g}s between cycles.\n"
        f"Approved verification: {json.dumps(plan.verification_commands)}\n"
        "Eligible repository text is sent to the selected provider. "
        "Edits stay in an isolated worktree for review. The terminal must remain open."
    )
