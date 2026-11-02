# token_maxxxer

A local development-task toolkit with configurable AI providers: **Claude API**,
**OpenAI API**, and a planned **GitHub Copilot SDK** integration.

The repository, Python package, and command are named `token_maxxxer`.
Python 3.11+, macOS and Linux. [Roadmap](roadmap.md) · [Checkpoints and rollbacks](checkpoint.md).

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
| GitHub Copilot | Planned; selecting it returns an explicit unsupported-provider error |
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

With no subcommand, the CLI opens an interactive picker. Select a discovered
repository, a recent selection, or enter another local path (including `file://`
URLs). It then lists repository and installed skills and suggests a repository
skill, falling back to the built-in `improve-code` skill. You choose the skill,
maximum duration, call limit and optional verification command before starting.
On first use without a configuration file, enter the provider and an explicit
model ID. The CLI remembers those settings and your recent selections privately.

To make the command available outside this checkout, install it with
`uv tool install --editable .`, then run `token_maxxxer` from any directory.

The equivalent explicit invocation is:

```bash
# Global options precede the subcommand. Use a clean Git repository.
uv run token_maxxxer --config examples/token_maxxxer.yaml night /path/to/repo \
  --skill builtin:improve-code --hours 8 --max-calls 100 \
  --verify 'uv run pytest -q' --dry-run

# Remove --dry-run to confirm interactively, or replace it with --yes to start.
# Configuration-free alternative: night /path/to/repo --provider claude --model YOUR_MODEL
```

`night` starts immediately in the foreground. It does not evaluate `schedule`
windows or use the imported task queue. Keep the terminal open and the machine
running. Each session creates a unique `token_maxxxer/night-*` branch and
worktree from the recorded HEAD; the selected working tree is preserved.
Verification commands are user-approved argument arrays, parsed with quoting
but without a shell. Repository code and checks must be trusted: a worktree is
Git isolation, not an operating-system sandbox.

The agent can list/read eligible tracked UTF-8 files, create/replace text files
in its worktree, read selected skill resources and run approved checks. It
excludes ignored files, credential filenames, Git metadata, symlinks, common
binary formats and files above 64 KiB. Reads are redacted for recognized
credentials; eligible project content is sent to the selected API provider.
It loads tracked `AGENTS.md` instructions, including nested directory rules.

Skills are Markdown instructions, not executable plugins. External MCP tools,
subagents and arbitrary shell commands referenced by a skill are unavailable;
the agent must report that limitation. `--skill auto` uses local discovery
without an inference request. Use `--skill ID` or an explicit `SKILL.md` path to
select another skill; `--mode review` provides file reads without modifications
or verification commands. See the [session contract](docs/night-cli.md).

The skill repeats only while useful work remains, pausing 60 seconds between
cycles (`--interval` changes that delay). The session stops at completion, its
deadline, its call limit, an API error, or an interrupt. The default ceiling is
eight hours and 100 calls; these limits do not guarantee an exact price.
Authentication and quota errors stop execution without provider fallback.

```bash
uv run token_maxxxer repos --root /path/to/projects
uv run token_maxxxer skills --repo /path/to/repo
uv run token_maxxxer sessions
uv run token_maxxxer sessions SESSION_ID
```

History, a provider/model profile and session records live under
`${XDG_STATE_HOME:-~/.local/state}/token_maxxxer`. Override this with the global
`--state-dir` option; storage must be outside the selected repository. Records
use private permissions and atomic replacement. A session retains `session.json`,
`report.md` and its worktree, with API-call counts, observed usage, verification
results and remaining review work. CLI progress is written to stderr, preserving
`--json` output. Reports retain the latest 50 cycle summaries and check results.

Changed work always needs human review; the runner never commits, pushes or
merges it. Use `git -C WORKTREE status` and `git -C WORKTREE diff` to inspect it
(new files appear in status). Failed/interrupted work is retained. A crash may
leave a `running` record; it is inspectable and is never automatically replayed.
Durable resume and background services remain future work.

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

## Select a provider

The complete example is [examples/token_maxxxer.yaml](examples/token_maxxxer.yaml).
A model is required. The application never substitutes a model or provider.

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
does not guarantee an exact financial budget. Neither adapter retries
requests automatically or falls back to another provider after an error.

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
├── results.py                # shared generation results and public diagnostics
├── queue.py, storage.py       # atomic imports and versioned SQLite
├── cli.py, doctor.py          # user commands and read-only diagnostics
├── repositories.py, skills.py # local discovery, recent paths and skill instructions
├── night.py, night_cli.py     # isolated overnight sessions and interactive selection
├── file_tools.py              # bounded file operations in the selected worktree
├── verification.py            # approved commands and process-group cancellation
├── local_state.py             # private atomic history and session records
└── json_io.py, redaction.py   # strict JSON handling and credential redaction
```

The retired subscription CLI transport, subprocess runner, wire parser, fixtures,
and archived CLI contract have been removed. Their history remains available
through Git checkpoints. LangGraph, LangChain Core, and a graph checkpointer
will be installed when the durable workflow is implemented, rather than kept as
unused dependencies. The application database and future workflow checkpoints
have separate configured locations.

Copilot will use the same `Provider` interface with its official SDK and GitHub
authentication. `provider.name: copilot` is recognized but rejected until that
adapter is implemented. No private Copilot endpoint or implicit reuse of `gh`
credentials is used. See [provider contracts](docs/providers.md).

## Development and migration

```bash
uv run ruff format --check
uv run ruff check
uv run mypy
uv run pytest -q
uv build --no-sources
```

Tests use simulated HTTP and temporary repositories. CI covers Python 3.11 and
3.13 on macOS and Linux. See [CONTRIBUTING.md](CONTRIBUTING.md).
All maintained documentation, code messages, examples, and test descriptions
are written in English. Prompts and generated responses may use any language.

From the prototype, update imports, commands, and configuration to
`token_maxxxer`, add `provider`, and set `authentication.mode` to `api_key`.
Credential reference variables use the `TOKEN_MAXXXER_` prefix. The shared
result type is now `GenerationResult`; `response_id` replaces the misleading
`session_id`, and unused subprocess fields have been removed.

No local data or Keychain entry is automatically renamed or deleted. To retain
an existing database, keep its explicit path in `storage.database`; its SQLite
application ID and schema remain compatible. Back up local data separately.
