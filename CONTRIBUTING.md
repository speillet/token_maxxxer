# Contributing

Use Python 3.11 or newer on macOS or Linux. Install from the committed lockfile:

```bash
uv sync --locked
uv run ruff format --check
uv run ruff check
uv run mypy
uv run pytest -q
uv build --no-sources
```

## Development standards

- Keep routing deterministic and provider integrations behind `Provider`.
  Claude and OpenAI use their official APIs; Copilot will use its official SDK
  and authorized GitHub credentials.
- Validate configuration and task input with Pydantic. Reject unknown fields
  and repository paths that are not explicitly allowed.
  An explicit night-session selection grants access to that repository for
  that session; it does not change the imported task queue's allowlist.
- Pass external commands as argument arrays without a shell. Define timeouts
  and cancellation behavior before introducing a new external process.
- Do not extract OAuth credentials or include authentication values in logs.
  Diagnostics must expose only approved metadata; resolve secrets only for an
  explicit operation that needs them.
- Persist timezone-aware timestamps in UTC and use IANA names for local schedules.
- Keep `list`, `doctor`, and `--dry-run` free of queue and repository mutations.
- Keep the application database separate from future workflow checkpoints.
  Version migrations and reject unknown databases or newer schemas.
- Test changed behavior, failures, and trust boundaries. Use simulated HTTP and
  temporary repositories; tests must never call a real AI API.
  Exercise night-session limits, isolation, typed actions, verification and
  interruption with simulated providers. Keep prompts and file contents out of
  persisted journals; record only approved metadata and redacted check output.
- Add modules and dependencies when they become necessary. Remove abandoned
  implementations and their tests while preserving relevant security coverage.
- Write maintained documentation, user-facing messages, examples, and test
  descriptions in English. Keep intentional Unicode test coverage.

## Changes, pull requests, and rollbacks

Use short branches and Conventional Commits, with one responsibility per commit.
Before a PR, run the checks above and update `docs/checkpoint.md`, completed
`docs/roadmap.md` items, the README's available commands and the relevant guide
in `docs/`. Mark operational validation complete
only with real evidence. Documentation and simulated transports do not establish
real account access; successful text generation does not verify a Git task.

Use the PR template sections Summary, Evidence, and Merge Danger. Explain the
behavior, validation, limitations, and rollback. Keep PR titles and descriptions
in English. Merge only relevant changes, preserve commit history, and remove
obsolete branches once their work is integrated or explicitly superseded.

After publication, use `git revert` rather than rewriting shared history.
Back up databases and unverified worktrees separately before schema changes.
Git rollback does not restore `.env`, Keychain entries, or other local data;
see [docs/checkpoint.md](docs/checkpoint.md).
