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
| GitHub Copilot | Planned; selecting it returns an explicit unsupported-provider error |
| Code-editing agent, Git worktrees, and task verification | Planned |
| Durable workflow, scheduling, and system services | Planned |

`query` returns generated text. It does not read or edit a repository, run local
commands, or mark a task as successful. Tests use simulated responses and do not
verify access to a real provider account or incur API charges.

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
remain valid even when they use an older service identifier. `query` retrieves
only the selected provider's credential, immediately before its explicit API
request. On Linux, supply the key through the process environment; macOS
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
