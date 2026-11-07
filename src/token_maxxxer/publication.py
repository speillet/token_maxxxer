"""Deterministic Git/GitHub delivery; publishing is never a model tool."""

import os
import re
import shlex
import shutil
import stat
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import ConfigDict, Field, field_validator

from token_maxxxer.commands import run_command
from token_maxxxer.credentials import KEY_VARIABLES, REFERENCE_VARIABLES
from token_maxxxer.file_tools import MAX_FILE_BYTES, safe_relative_path
from token_maxxxer.json_io import load_unique_json
from token_maxxxer.local_state import write_private_text
from token_maxxxer.models import Model
from token_maxxxer.redaction import redact
from token_maxxxer.repositories import git

_REPOSITORY = r"[A-Za-z0-9][A-Za-z0-9_-]{0,38}/[A-Za-z0-9_.-]{1,100}"
_OID = re.compile(r"^[a-f0-9]{40}(?:[a-f0-9]{24})?$")
_BRANCH = re.compile(r"^token_maxxxer/night-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")


class PublicationError(ValueError):
    """A fixed diagnostic code, never raw command output."""


class PublicationConfig(Model):
    repository: str = Field(pattern=f"^{_REPOSITORY}$")
    base_branch: str = Field(min_length=1, max_length=200)

    @field_validator("base_branch")
    @classmethod
    def safe_base(cls, value: str) -> str:
        if (
            value.startswith(("-", "/", "."))
            or value.endswith(("/", ".", ".lock"))
            or any(part in value for part in ("..", "@{", "//"))
            or any(char in value for char in " ~^:?*[\\")
            or any(ord(char) < 33 or ord(char) > 126 for char in value)
            or value == "@"
            or any(part.startswith(".") or part.endswith(".lock") for part in value.split("/"))
        ):
            raise ValueError("base must be a safe branch name")
        return value

    @property
    def url(self) -> str:
        return f"https://github.com/{self.repository}.git"

    @property
    def gh_repository(self) -> str:
        return f"github.com/{self.repository}"


class PublicationRecord(Model):
    model_config = ConfigDict(frozen=False)
    phase: Literal[
        "idle",
        "committing",
        "committed",
        "pushing",
        "pushed",
        "opening_pr",
        "published",
        "blocked",
        "uncertain",
    ] = "idle"
    commits: list[str] = Field(default_factory=list)
    pushed_commit: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    error: str | None = None


def github_repository(remote: str) -> str:
    if remote.startswith("git@github.com:"):
        path = remote.removeprefix("git@github.com:")
    else:
        try:
            parsed = urlparse(remote)
            port = parsed.port
        except ValueError:
            raise PublicationError("origin_must_identify_github_repository") from None
        if (
            parsed.hostname != "github.com"
            or parsed.query
            or parsed.fragment
            or port
            or parsed.scheme not in ("https", "ssh")
            or (parsed.scheme == "https" and (parsed.username or parsed.password))
            or (parsed.scheme == "ssh" and parsed.username != "git")
        ):
            raise PublicationError("origin_must_identify_github_repository")
        path = parsed.path.removeprefix("/")
    path = path.removesuffix(".git")
    if not re.fullmatch(_REPOSITORY, path) or path.split("/")[1] in (".", ".."):
        raise PublicationError("origin_must_identify_github_repository")
    return path


def publication_config(repository: Path, base: str | None) -> PublicationConfig:
    urls = git(repository, "remote", "get-url", "--all", "origin").splitlines()
    if len(urls) != 1:
        raise PublicationError("origin_must_have_one_url")
    name = github_repository(urls[0])
    if base is None:
        reference = git(
            repository,
            "symbolic-ref",
            "--quiet",
            "refs/remotes/origin/HEAD",
            allowed_returncodes=(0, 1),
        ).strip()
        if not reference.startswith("refs/remotes/origin/"):
            raise PublicationError("pass_base_branch_when_origin_head_is_unknown")
        base = reference.removeprefix("refs/remotes/origin/")
    return PublicationConfig(repository=name, base_branch=base)


class Publisher:
    def __init__(
        self,
        config: PublicationConfig,
        root: Path,
        *,
        deadline: float = float("inf"),
        clock: Callable[[], float] = time.time,
    ):
        self.config, self.root, self.deadline, self.clock = config, root, deadline, clock
        self.gh = shutil.which("gh") or "gh"
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
            and key not in {*KEY_VARIABLES.values(), *REFERENCE_VARIABLES.values()}
        }
        self.environment.update(
            GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1", GH_HOST="github.com"
        )

    def _command(
        self, arguments: list[str], *, allowed: tuple[int, ...] = (0,), limit: int = 262_144
    ) -> bytes:
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise PublicationError("publication_deadline_reached")
        result = run_command(
            arguments, self.root, min(60, remaining), self.environment, max_output_bytes=limit
        )
        if result.timed_out or result.truncated or result.exit_code not in allowed:
            raise PublicationError("publication_command_failed")
        return result.output

    def _git(
        self,
        *arguments: str,
        allowed: tuple[int, ...] = (0,),
        limit: int = 262_144,
        literal: bool = True,
    ) -> bytes:
        return self._command(
            [
                "git",
                *(["--literal-pathspecs"] if literal else []),
                "-c",
                "core.fsmonitor=false",
                "-c",
                "http.followRedirects=false",
                "-c",
                "credential.helper=",
                "-c",
                f"credential.helper=!{shlex.quote(self.gh)} auth git-credential",
                *arguments,
            ],
            allowed=allowed,
            limit=limit,
        )

    def _gh(self, *arguments: str) -> bytes:
        return self._command([self.gh, *arguments, "--repo", self.config.gh_repository])

    def preflight(self) -> None:
        if not shutil.which("gh"):
            raise PublicationError("github_cli_required")
        data = load_unique_json(
            self._command(
                [
                    self.gh,
                    "repo",
                    "view",
                    self.config.gh_repository,
                    "--json",
                    "nameWithOwner,viewerPermission",
                ]
            ).decode("utf-8")
        )
        if (
            not isinstance(data, dict)
            or str(data.get("nameWithOwner", "")).lower() != self.config.repository.lower()
            or data.get("viewerPermission") not in ("WRITE", "MAINTAIN", "ADMIN")
        ):
            raise PublicationError("github_write_access_required")
        self._git("var", "GIT_AUTHOR_IDENT")
        self._git("var", "GIT_COMMITTER_IDENT")
        if self._git(
            "config", "--get-regexp", r"^url\..*\.(insteadof|pushinsteadof)$", allowed=(0, 1)
        ):
            raise PublicationError("git_url_rewrites_are_not_supported")

    def fetch_base(self, session_id: str) -> str:
        if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}", session_id):
            raise PublicationError("invalid_session_reference")
        reference = f"refs/token_maxxxer/{session_id}/base"
        self._git(
            "fetch",
            "--no-tags",
            "--no-recurse-submodules",
            "--no-write-fetch-head",
            self.config.url,
            f"refs/heads/{self.config.base_branch}:{reference}",
        )
        return self._oid(self._git("rev-parse", "--verify", f"{reference}^{{commit}}"))

    @staticmethod
    def _oid(value: bytes) -> str:
        oid = value.decode("ascii").strip()
        if not _OID.fullmatch(oid):
            raise PublicationError("invalid_git_object")
        return oid

    def _remote_head(self, branch: str) -> str | None:
        raw = self._git(
            "ls-remote", "--exit-code", self.config.url, f"refs/heads/{branch}", allowed=(0, 2)
        )
        if not raw:
            return None
        entries = raw.decode("ascii").strip().split("\t")
        if len(entries) != 2 or entries[1] != f"refs/heads/{branch}":
            raise PublicationError("unexpected_remote_reference")
        return self._oid(entries[0].encode())

    def _find_pr(self, branch: str) -> dict[str, object] | None:
        data = load_unique_json(
            self._gh(
                "pr",
                "list",
                "--head",
                branch,
                "--base",
                self.config.base_branch,
                "--state",
                "all",
                "--limit",
                "10",
                "--json",
                "number,url,state,isDraft,headRefName,headRefOid,baseRefName,isCrossRepository,body",
            ).decode("utf-8")
        )
        if not isinstance(data, list) or len(data) > 1:
            raise PublicationError("ambiguous_pull_request")
        if not data:
            return None
        pr = data[0]
        if (
            not isinstance(pr, dict)
            or pr.get("state") != "OPEN"
            or pr.get("isDraft") is not True
            or pr.get("isCrossRepository") is not False
            or pr.get("headRefName") != branch
            or pr.get("baseRefName") != self.config.base_branch
        ):
            raise PublicationError("pull_request_is_not_an_open_session_draft")
        number = pr.get("number")
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or number <= 0
            or pr.get("url") != f"https://github.com/{self.config.repository}/pull/{number}"
        ):
            raise PublicationError("unexpected_pull_request_metadata")
        return pr

    def _index(self) -> dict[str, tuple[str, str]]:
        entries = {}
        for entry in self._git("ls-files", "--stage", "-z").split(b"\0"):
            if not entry:
                continue
            header, path = entry.decode("utf-8").split("\t", 1)
            mode, oid, stage = header.split()
            if stage != "0":
                raise PublicationError("unmerged_index")
            entries[path] = (mode, self._oid(oid.encode()))
        return entries

    def _snapshot(self, owned: set[str]) -> dict[str, tuple[str, str]]:
        if self._git("diff", "--cached", "--name-only", "-z"):
            raise PublicationError("unexpected_staged_changes")
        tracked = self._git("diff", "HEAD", "--name-only", "--no-renames", "-z")
        untracked = self._git("ls-files", "--others", "--exclude-standard", "-z")
        paths = {name.decode("utf-8") for name in (tracked + untracked).split(b"\0") if name}
        if not paths.issubset(owned):
            raise PublicationError("unowned_worktree_changes")
        if not paths:
            return {}
        for name in paths:
            if redact(name) != name:
                raise PublicationError("credential_in_publication_path")
            path = self.root / safe_relative_path(name)
            for component in (path, *path.parents):
                if component == self.root:
                    break
                if component.is_symlink():
                    raise PublicationError("unsafe_publication_path")
            info = path.stat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_size > MAX_FILE_BYTES
            ):
                raise PublicationError("unsafe_publication_file")
            if self._git("check-ignore", "--no-index", "--", name, allowed=(0, 1), literal=False):
                raise PublicationError("ignored_publication_file")
        self._git("add", "--", *sorted(paths))
        snapshot = {name: value for name, value in self._index().items() if name in paths}
        staged = {
            name.decode()
            for name in self._git("diff", "--cached", "--name-only", "-z").split(b"\0")
            if name
        }
        if set(snapshot) != paths or staged != paths:
            raise PublicationError("unexpected_staged_changes")
        for mode, oid in snapshot.values():
            if mode not in ("100644", "100755"):
                raise PublicationError("unsafe_publication_mode")
            raw = self._git("cat-file", "blob", oid, limit=MAX_FILE_BYTES + 1)
            content = raw.decode("utf-8")
            if len(raw) > MAX_FILE_BYTES or "\0" in content or redact(content) != content:
                raise PublicationError("credential_or_binary_in_publication")
        return snapshot

    def publish(
        self,
        branch: str,
        owned: set[str],
        skill: str,
        summaries: list[str],
        record: PublicationRecord,
        directory: Path,
        persist: Callable[[], None],
    ) -> None:
        if not _BRANCH.fullmatch(branch):
            raise PublicationError("invalid_publication_branch")
        if redact(skill) != skill or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", skill):
            raise PublicationError("unsafe_publication_skill_name")
        try:
            if self._git("symbolic-ref", "--short", "HEAD").decode().strip() != branch:
                raise PublicationError("unexpected_worktree_branch")
            if self._remote_head(branch) != record.pushed_commit:
                raise PublicationError("remote_branch_changed")
            existing = self._find_pr(branch)
            if record.pr_number and (
                not existing
                or existing["number"] != record.pr_number
                or existing.get("headRefOid") != record.pushed_commit
            ):
                raise PublicationError("pull_request_changed")
            before = self._oid(self._git("rev-parse", "HEAD"))
            if record.commits and before != record.commits[-1]:
                raise PublicationError("local_branch_changed")
            snapshot = self._snapshot(owned)
            if not snapshot:
                return
            record.phase = "committing"
            persist()
            kind = "docs" if all(Path(name).suffix == ".md" for name in snapshot) else "fix"
            self._git("commit", "-m", f"{kind}(agent): apply verified {skill[:30]} improvements")
            commit = self._oid(self._git("rev-parse", "HEAD"))
            parents = self._git("rev-list", "--parents", "-n", "1", commit).decode().split()
            changed = {
                name.decode()
                for name in self._git(
                    "diff", before, commit, "--name-only", "--no-renames", "-z"
                ).split(b"\0")
                if name
            }
            if (
                parents != [commit, before]
                or changed != set(snapshot)
                or any(self._index().get(name) != value for name, value in snapshot.items())
                or self._git("diff", "--name-only", "-z")
                or self._git("diff", "--cached", "--name-only", "-z")
                or self._git("ls-files", "--others", "--exclude-standard", "-z")
            ):
                raise PublicationError("commit_hooks_changed_verified_snapshot")
            record.commits.append(commit)
            record.phase = "committed"
            persist()
            if record.pr_number:
                current = self._find_pr(branch)
                if not current or current.get("headRefOid") != record.pushed_commit:
                    raise PublicationError("pull_request_changed")
            record.phase = "pushing"
            persist()
            try:
                self._git(
                    "push",
                    "--porcelain",
                    "--no-follow-tags",
                    "--recurse-submodules=no",
                    f"--force-with-lease=refs/heads/{branch}:{record.pushed_commit or ''}",
                    self.config.url,
                    f"{commit}:refs/heads/{branch}",
                )
            except PublicationError:
                if self._remote_head(branch) != commit:
                    raise PublicationError("push_outcome_uncertain") from None
            record.pushed_commit = commit
            record.phase = "pushed"
            persist()
            body = directory / "pull-request.md"
            notes = redact("\n\n".join(summaries[-3:]))[:12000]
            fence = "`" * (max([len(run) for run in re.findall(r"`+", notes)] or [2]) + 1)
            text = (
                f"## Summary\n\nApply verified improvements using `{skill}`.\n\n"
                f"Agent notes (review required):\n\n{fence}\n{notes}\n{fence}\n\n"
                f"## Evidence\n\n- {len(record.commits)} verified improvement batch(es).\n"
                "- Approved verification commands passed before publication.\n\n"
                "## Merge Danger\n\n**Door:** two-way\n\n"
                "Revert the commits to roll back; retained local work is separate.\n\n"
                "**Blast Radius:** repository\n\nReview the diff and CI before merging.\n"
            )
            write_private_text(body, text)
            record.phase = "opening_pr"
            persist()
            try:
                if existing:
                    self._gh("pr", "edit", str(existing["number"]), "--body-file", str(body))
                else:
                    self._gh(
                        "pr",
                        "create",
                        "--head",
                        branch,
                        "--base",
                        self.config.base_branch,
                        "--title",
                        f"Improve repository with {skill[:60]}",
                        "--body-file",
                        str(body),
                        "--draft",
                        "--no-maintainer-edit",
                    )
            except PublicationError:
                pass  # Read back before deciding whether creation actually failed.
            pr = self._find_pr(branch)
            if pr is None or pr.get("headRefOid") != commit or pr.get("body") != text:
                raise PublicationError("pull_request_outcome_uncertain")
            record.pr_number, record.pr_url = int(str(pr["number"])), str(pr["url"])
            record.phase, record.error = "published", None
            persist()
        except BaseException as error:
            uncertain = record.phase in ("committing", "pushing", "opening_pr")
            record.phase = "uncertain" if uncertain else "blocked"
            record.error = (
                str(error) if isinstance(error, PublicationError) else "publication_interrupted"
            )
            with suppress(Exception):
                persist()
            if isinstance(error, Exception):
                raise PublicationError(record.error) from None
            raise
