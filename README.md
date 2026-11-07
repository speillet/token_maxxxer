# token_maxxxer

Run bounded AI coding skills on your local repositories overnight: isolated Git
worktrees, approved checks, Claude/OpenAI APIs, nothing merged automatically.

The repository, Python package, and command are named `token_maxxxer`.
Python 3.11+, macOS and Linux. Providers: **Claude API**, **OpenAI API**,
**Codex CLI**, and the optional **GitHub Copilot SDK**. See the [documentation](#documentation).

## Current capabilities

| Capability | Status |
| --- | --- |
| Validated configuration and domain models | Available |
| Atomic, idempotent YAML imports and a SQLite task queue | Available |
| Read-only diagnostics, task listing, and previews | Available |
| Claude and OpenAI text generation | Available through `query`; tested with simulated HTTP |
| Private credential references | Available |
| Interactive repository picker and recent local-path history | Available |
| Repository/user skills and built-in code review/improvement | Available |
| Bounded overnight skill sessions in isolated Git worktrees | Available; approved checks, reports, no automatic merge |
| Headless draft-PR delivery | `improve` or `night --publish-pr`; verified cycles, supervised commit/push, no automatic merge |
| Codex CLI / GitHub Copilot SDK | Text-action adapters using native authentication; Copilot requires its optional extra |
| Explicit provider fallback on exhausted credits | Configured order, preserved context, shared call/deadline limits |
| Execution of imported queue tasks | Planned; queue previews remain read-only |
| Durable workflow, scheduling, and system services | Planned |

`query` returns generated text. It does not read or edit a repository, run local
commands, or mark a task as successful. Tests use simulated responses and do not
verify access to a real provider account or incur API charges.

## Start an overnight session

```bash
uv sync --locked
uv run token_maxxxer
```

With no subcommand, the CLI opens an interactive picker: choose a local
repository, a skill, the provider/model, a maximum duration, a call limit and an
optional verification command. The equivalent explicit invocation is:

```bash
# Global options precede the subcommand. Use a clean Git repository.
uv run token_maxxxer --config examples/token_maxxxer.yaml night /path/to/repo \
  --skill builtin:improve-code --hours 8 --max-calls 100 \
  --verify 'uv run pytest -q' --dry-run
```

Remove `--dry-run` to confirm interactively, or replace it with `--yes` to start.
Each session works in its own `token_maxxxer/night-*` branch and worktree; the
selected working tree is preserved, and changed work always needs human review.
Repository code and checks must be trusted: a worktree is Git isolation, not an
operating-system sandbox. The [overnight session guide](docs/night-cli.md)
covers the picker, tool scope, limits, session records and review.

## Install and inspect

```bash
uv sync --locked
uv run token_maxxxer --help
uv run token_maxxxer --config examples/token_maxxxer.yaml doctor
uv run token_maxxxer --config examples/token_maxxxer.yaml tasks import examples/tasks.yaml
uv run token_maxxxer --config examples/token_maxxxer.yaml tasks list
uv run token_maxxxer --config examples/token_maxxxer.yaml run --dry-run
```

The example allows this repository root and stores tasks in
`var/token_maxxxer.sqlite`. Adjust repository paths and tasks before using your
own projects. Relative paths resolve from their YAML file, including default
storage paths. Without `--config`, the command expects `./token_maxxxer.yaml`.
Private configuration files are excluded from Git.

`doctor` checks Git, allowed repository roots, storage locations, provider
settings, and whether a credential or reference is configured. It does not read
a Keychain secret, call a provider API, or authenticate the configured key.
Claude Code and a Claude subscription are not required.

For a single future window under a local supervisor, see
[one supervised night](docs/one-shot-night.md). The example resolves credentials
before waiting and records whether the job is actually ready; it does not
install a recurring service or implement durable resume.

## Select a provider

The complete example is [examples/token_maxxxer.yaml](examples/token_maxxxer.yaml).
A model is required. Another provider/model is used only when explicitly listed
as an authorized fallback.

```yaml
provider:
  name: claude
  model: claude-sonnet-5-5
  max_output_tokens: 4096
  timeout_seconds: 60

authentication:
  mode: api_key
  env_file: ../.env
```

For OpenAI, replace the provider block with:

```yaml
provider:
  name: openai
  model: gpt-5.4-mini
  max_output_tokens: 4096
  timeout_seconds: 60
```

Model identifiers are configurable examples; verify access in your provider
account. An API key uses that account's API allocation. The output-token limit
does not guarantee an exact financial budget. API adapters do not retry requests
automatically. Exhausted quota can select an explicitly authorized fallback:

```bash
uv run token_maxxxer night /path/to/clean-repo \
  --provider claude --model claude-sonnet-5-5 \
  --fallback codex:gpt-6.1-sol --yes
```

Codex reuses `codex login`, including ChatGPT sign-in. Install Copilot support
with `uv sync --locked --extra copilot`, then authorize it with another
`--fallback copilot:MODEL`. See the [fallback example](examples/provider-fallbacks.yaml)
and [provider guide](docs/providers.md) for credentials, order and limits.
Edit sessions still require a clean local checkout; provider fallback does not
snapshot uncommitted source work.

## Keep credentials outside Git

Only credentials for the selected provider are considered, in this order:

1. A process environment variable: `ANTHROPIC_API_KEY` for Claude or
   `OPENAI_API_KEY` for OpenAI.
2. A private credential reference in the environment or local `.env` file.
   Environment references take priority over file references.

```dotenv
TOKEN_MAXXXER_CLAUDE_CREDENTIAL_REF=keychain://token_maxxxer.claude.api/token_maxxxer
# TOKEN_MAXXXER_OPENAI_CREDENTIAL_REF=keychain://token_maxxxer.openai.api/token_maxxxer
```

The service and account identify entries in macOS Keychain. Existing references
remain valid even when they use an older service identifier. `query` and confirmed
`night` sessions retrieve only the selected provider's credential. Without a
configuration file, `night` uses the current directory's `.env` (or `--env-file`)
and remembers that reference-file path with the provider profile.
On Linux, supply the key through the process environment; macOS
Keychain references are not supported there.

The `.env` reader handles known references without executing the file,
interpolating values, or changing the global environment. It rejects plaintext
API key values in that file. Keep local file permissions at `0600`.
Only [.env.example](.env.example), which contains no secret, is tracked.
Rotate keys in the credential manager or process environment, never in Git.

## Generate text

After configuring a key and model, create a UTF-8 prompt file and explicitly run:

```bash
uv run token_maxxxer --config examples/token_maxxxer.yaml query --prompt-file prompt.txt
```

This command sends the prompt to the configured provider and can consume its API
allocation. Use `--prompt-file -` to read stdin and `--json` for the normalized
result: `status`, `response_id`, `text`, `error_code`, `duration_seconds`, and
optional `usage`. Missing usage stays unknown rather than becoming zero.
Refusals, errors, incomplete messages, and unsupported tool calls are not successes.

Prompt indentation and whitespace are preserved. Prompts longer than 1,048,576
characters are rejected before credential resolution or API access; they are
never silently truncated.

Use `doctor` or `run --dry-run` to inspect configuration without an API request.
These commands and `tasks list` do not create a database or modify the queue or
repositories. Exit codes are `0` for success, `1` for a failed diagnostic or API
result, and `2` for invalid input or storage.

## Task queue

Import only explicit tasks from trusted YAML. Each task declares a stable ID,
an allowed repository root, an explicit Git base, a prompt, acceptance criteria,
and verification commands expressed as argument arrays. See
[examples/tasks.yaml](examples/tasks.yaml).

Higher priority runs first; ties preserve arrival order. Reimporting an identical
task creates no duplicate. Reusing an ID for a different definition rejects the
entire batch. Allowing a repository root does not implicitly allow subdirectories.

`run --once`, pause/resume, reports, and services are not implemented yet. Future
execution will prepare a worktree per task, expose explicitly approved tools,
and require verification before declaring a task successful. An empty queue
ends work; the application does not invent tasks to consume tokens.

## Architecture

```text
src/token_maxxxer/
├── config.py, models.py       # validated configuration and domain data
├── credentials.py            # private references and on-demand resolution
├── providers.py              # Provider, Claude Messages, OpenAI Responses
├── provider_routing.py        # explicit quota fallback and per-attempt selection
├── local_providers.py         # Codex CLI and isolated Copilot SDK worker adapter
├── results.py                # shared generation results and public diagnostics
├── queue.py, storage.py       # atomic imports and versioned SQLite
├── cli.py, doctor.py          # user commands and read-only diagnostics
├── repositories.py, skills.py # local discovery, recent paths and skill instructions
├── night.py, night_cli.py     # isolated overnight sessions and interactive selection
├── publication.py            # supervised commit, push and draft-PR delivery
├── commands.py               # bounded subprocesses and private runtime input
├── file_tools.py              # bounded file operations in the selected worktree
├── verification.py            # approved commands and process-group cancellation
├── local_state.py             # private atomic history and session records
└── json_io.py, redaction.py   # strict JSON handling and credential redaction
```

LangGraph, LangChain Core, and a graph checkpointer will be installed when the
durable workflow is implemented, rather than kept as unused dependencies. The
application database and future workflow checkpoints have separate configured
locations.

Codex and Copilot use the same text `Provider` interface. Their own tools are
disabled; the supervisor controls file access, verification and publication.
Authentication stays in the official CLI/SDK. No private inference endpoint or
OAuth credential extraction is used.

## Development

```bash
uv run ruff format --check
uv run ruff check
uv run mypy
uv run pytest -q
uv build --no-sources
```

Tests use simulated HTTP and temporary repositories. CI covers Python 3.11 and
3.13 on macOS and Linux. All maintained documentation, code messages, examples,
and test descriptions are written in English. Prompts and generated responses
may use any language.

## Documentation

| Document | Contents |
| --- | --- |
| [docs/night-cli.md](docs/night-cli.md) | Overnight sessions: picker, explicit invocation, tool scope, limits, records and review |
| [docs/providers.md](docs/providers.md) | Provider contract, result statuses, credentials and official API references |
| [docs/headless-pr-agent.md](docs/headless-pr-agent.md) | Headless delivery, verification and draft-PR publication |
| [docs/roadmap.md](docs/roadmap.md) | Milestones and remaining work |
| [docs/checkpoint.md](docs/checkpoint.md) | Delivery history, rollback points, procedure and prototype migration |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development standards, checks, pull requests and rollbacks |
