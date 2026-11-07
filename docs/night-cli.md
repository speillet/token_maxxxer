# Interactive overnight skills

`token_maxxxer` runs a selected skill against a local Git repository for a bounded
time. Edits happen in an isolated worktree and always need human review. By
default, sessions retain local work without commits or pushes. `improve` and
`night --publish-pr` explicitly enable supervised draft-PR delivery; see the
[publication guide](headless-pr-agent.md). No session merges automatically.

## Start a session

```bash
uv sync --locked
uv run token_maxxxer
```

With no subcommand, the CLI opens an interactive picker. It combines recently
selected local paths, configured repositories, the current repository, and a
bounded discovery of nearby projects (siblings of the current directory by
default). You can also enter another local path or a `file://` URL; remote URLs
are not cloned. History stores canonical local paths and suggests existing
entries first.

The picker then offers repository and user-installed `SKILL.md` files and the
built-in `improve-code` and `code-review` skills. It suggests a repository skill,
falling back to `improve-code`; suggestions use local metadata, not an API call.
You choose the skill, maximum duration, call limit and an optional verification
command before starting. On first use without a configuration file, enter the
provider and an explicit model ID; a model is never silently substituted. The
CLI remembers those settings and your recent selections privately.

To make the command available outside this checkout, install it with
`uv tool install --editable .`, then run `token_maxxxer` from any directory.

## Explicit invocation

`night` accepts explicit arguments for unattended invocation:

```bash
# Global options precede the subcommand. Use a clean Git repository.
uv run token_maxxxer --config examples/token_maxxxer.yaml night /path/to/repo \
  --skill builtin:improve-code --hours 8 --max-calls 100 \
  --verify 'uv run pytest -q' --dry-run

# Remove --dry-run to confirm interactively, or replace it with --yes to start.
# Configuration-free alternative: night /path/to/repo --provider claude --model YOUR_MODEL
```

A preview shows the repository, skill, provider/model, mode, limits and
verification commands without retrieving credentials, creating files or calling
an API. Execution requires confirmation or `--yes`.

`--skill auto` uses local discovery without an inference request. Use
`--skill ID` or an explicit `SKILL.md` path to select another skill;
`--mode review` provides file reads without modifications or verification
commands. Inspection commands make no API request:

```bash
uv run token_maxxxer repos --root /path/to/projects
uv run token_maxxxer skills --repo /path/to/repo
uv run token_maxxxer sessions
uv run token_maxxxer sessions SESSION_ID
```

`night` starts immediately in the foreground. It does not evaluate `schedule`
windows or use the imported task queue. Keep the terminal open and the machine
running.

## Execution contract

- Claude/OpenAI APIs, Codex CLI and the optional Copilot SDK share the provider
  interface. Provider errors stop the session
  unless a configured fallback explicitly authorizes that quota/rate-limit status.
- Review mode exposes bounded, redacted reads of eligible tracked text files.
- Edit mode requires a clean repository and creates a unique
  `token_maxxxer/night-*` branch and worktree from the recorded HEAD. All writes
  stay in that worktree; the selected working tree is preserved. Git metadata,
  credential files, ignored files, symlinks and paths outside the root are denied.
- A typed JSON action protocol supports file reads, writes, approved verification
  commands and completion. No model-supplied shell command is executed.
- Only verification commands explicitly supplied by the user can execute. They
  are argument arrays, parsed with quoting but without a shell. Each has a
  timeout and process-group cancellation. A worktree is Git isolation, not an
  operating-system sandbox: repository code and verification commands must be
  trusted.
- Verification arguments must not contain credentials. Recognized secret values
  are rejected in every argument, as are options and `NAME=value` assignments
  whose name denotes a credential (`--token`, `--api-key`, `PASSWORD=...`).
  Positional words such as `pytest -k token` remain allowed. Check environments
  omit credential variables.
- Preview and cancellation never run Git status: its clean filters can execute
  repository-configured code. Cleanliness checks happen only after confirmation,
  before credential access.
- Signals and deadlines stop execution. Session metadata is persisted before
  external effects and after each action. A crashed session is inspectable but
  is never automatically replayed. No durable resume or background service is
  implied by the foreground command.

## Agent tools and file scope

The agent can list and read eligible tracked UTF-8 files, create or replace text
files in its worktree, read selected skill resources and run approved checks. It
excludes ignored files, known credential filenames, Git metadata, dependency and
cache directories, symlinks, common binary formats, lockfiles and files above
64 KiB. Reads are redacted for recognized credentials; eligible project content
is sent to the selected API provider. It loads tracked `AGENTS.md` instructions,
including nested directory rules.

Repository skill resources follow the tracked-file rules and are read from the
worktree in edit mode. For a user skill outside the repository, supporting-file
reads are confined to its selected directory, with the same size,
credential-name and symlink limits.

Skills are Markdown instructions, not executable plugins. Installing a skill
does not install its external tools: MCP tools, subagents and arbitrary shell
commands referenced by a skill are unavailable, and the agent must report that
limitation.

## Cycles and limits

Configure an authorized fallback with `--fallback codex:MODEL` or repeated
`--fallback PROVIDER:MODEL` flags. Quota exhaustion selects the next configured
provider and keeps the same context/worktree. Each rejected request and each
fallback attempt consumes one call slot; the deadline never resets. The journal
records provider/model attribution and transitions. Authentication errors,
timeouts and invalid responses do not switch providers. See [providers](providers.md)
for YAML configuration and Copilot installation/authentication.

The skill repeats only while it reports remaining useful work, pausing 60 seconds
between cycles (`--interval` changes that delay). It stops early when done; no
empty work is invented to consume tokens. The session stops at completion, its
deadline, its call limit, repeated tool denials, an API error, or an interrupt.

The default ceiling is eight hours and 100 calls. Reported token usage is
observed, not a price cap, and these limits do not guarantee an exact cost.
Authentication errors stop execution. Quota errors stop when no authorized
fallback remains or when the call/deadline limit prevents another attempt.

## State, records and reports

History, a provider/model profile and session records live under
`${XDG_STATE_HOME:-~/.local/state}/token_maxxxer`. Override this with the global
`--state-dir` option; storage must be outside the selected repository. Records
use private permissions and atomic replacement.

A session retains `session.json`, `report.md` and its worktree, with API-call
counts, observed usage, verification results and remaining review work. Prompts
and file contents are not journaled. Reports retain the latest 50 cycle
summaries and check results, redacted. A local failure records only the
exception class name, never its message. CLI progress is written to stderr,
preserving `--json` output.

## Review, keep or discard work

Changed work always needs human review. Reports preserve the branch and worktree
and mark edited work as `needs_review`. Inspect it with
`git -C WORKTREE status` (new files appear there) and `git -C WORKTREE diff`,
run your checks, then commit the changes you want to keep.

Failed or interrupted work is retained. A crash may leave a `running` record; it
is inspectable and is never automatically replayed. Before removing a run's
worktree or branch, back up valuable work and note the session's base commit,
which is the rollback reference. Git source rollback does not remove local
records or recover uncommitted edits; see [checkpoint.md](checkpoint.md).

## Acceptance checks

Use temporary Git repositories, simulated providers and a controllable clock.
Cover discovery/history, explicit paths, skill precedence, interactive selection,
network-free previews, isolated edits, denied secrets/symlinks/traversal,
verification failures/timeouts, repeated cycles, deadline/call limits, API
failures, interruption and inspectable session records. No test calls an AI API.
