"""Discover instruction-only skills without executing their scripts or plugins."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from yaml.tokens import AliasToken

from token_maxxxer.yaml_io import UniqueSafeLoader

MAX_SKILL_BYTES = 65_536
_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,99}$")


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    description: str
    instructions: str
    path: Path | None = None


_BUILTINS = (
    Skill(
        "builtin:improve-code",
        "improve-code",
        "Find and implement small, useful code improvements.",
        "Inspect project documentation, AGENTS.md and relevant code before changing anything. "
        "Find a concrete defect or a small improvement supported by evidence. "
        "Make a focused change and add meaningful tests when appropriate. "
        "Use approved checks if available. Never claim tests passed unless a tool ran them. "
        "Finish each cycle with a concise account of changes and unresolved issues. "
        "Continue only when another concrete, useful improvement remains. "
        "Respect repository conventions and avoid unrelated rewrites.",
    ),
    Skill(
        "builtin:code-review",
        "code-review",
        "Review code for concrete defects and report evidence.",
        "Inspect repository documentation and relevant source and tests. "
        "Identify actionable correctness problems with file paths and evidence. "
        "Do not write files. Do not invent findings. Summarize findings in the final report. "
        "Continue only if a specific unreviewed area remains.",
    ),
)


def load_skill(path: Path, *, source: str = "file") -> Skill:
    if path.is_symlink() or not path.is_file():
        raise ValueError("a skill must be a regular SKILL.md file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_SKILL_BYTES + 1)
    if len(raw) > MAX_SKILL_BYTES:
        raise ValueError("skill is too large (maximum 64 KiB)")
    try:
        content = raw.decode("utf-8")
        lines = content.splitlines()
        metadata: object = {}
        if lines and lines[0].strip() == "---":
            end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
            header = "\n".join(lines[1:end])
            if any(isinstance(token, AliasToken) for token in yaml.scan(header)):
                raise ValueError("skill metadata must not contain aliases")
            metadata = yaml.load(header, Loader=UniqueSafeLoader)
            content = "\n".join(lines[end + 1 :])
        if not isinstance(metadata, dict):
            raise ValueError("skill metadata must be a mapping")
        name = metadata.get("name", path.parent.name)
        description = metadata.get("description", "Local skill instructions")
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError("invalid skill name")
        if not isinstance(description, str) or not content.strip():
            raise ValueError("expected a description and nonempty skill instructions")
    except (UnicodeError, StopIteration, yaml.YAMLError, RecursionError) as exc:
        raise ValueError("invalid SKILL.md metadata or encoding") from exc
    return Skill(f"{source}:{name}", name, description[:500], content, path.resolve())


def discover_skills(repository: Path) -> list[Skill]:
    directories = [
        ("repo", repository / directory / "skills")
        for directory in (".agents", ".claude", ".codex")
    ]
    directories.extend(
        ("user", Path.home() / directory / "skills")
        for directory in (".agents", ".codex", ".claude")
    )
    directories.append(("user", Path.home() / ".codex/skills/.system"))
    result: list[Skill] = []
    seen_paths: set[Path] = set()
    seen_ids: set[str] = set()
    for source, directory in directories:
        if not directory.is_dir() or directory.is_symlink():
            continue
        for child in sorted(directory.iterdir())[:200]:
            path = child / "SKILL.md"
            if child.is_symlink() or path.resolve() in seen_paths:
                continue
            try:
                skill = load_skill(path, source=source)
            except (OSError, ValueError):
                continue
            seen_paths.add(path.resolve())
            if skill.id in seen_ids:
                skill = Skill(
                    f"{source}:{directory.parent.name}:{skill.name}",
                    skill.name,
                    skill.description,
                    skill.instructions,
                    skill.path,
                )
            seen_ids.add(skill.id)
            result.append(skill)
    return [*result, *_BUILTINS]


def select_skill(skills: list[Skill], selector: str | None, *, mode: str) -> Skill:
    if selector and selector != "auto":
        matches = [skill for skill in skills if selector in (skill.id, skill.name)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError("skill name is ambiguous; select its source-qualified ID")
        path = Path(selector).expanduser()
        if path.is_file():
            return load_skill(path)
        raise ValueError("skill was not found; use skills --repo PATH to list available IDs")
    # Repository instructions take precedence; unrelated user skills are never guessed.
    repository_skill = next((skill for skill in skills if skill.id.startswith("repo:")), None)
    fallback = "improve-code" if mode == "edit" else "code-review"
    return repository_skill or next(skill for skill in skills if skill.id == f"builtin:{fallback}")
