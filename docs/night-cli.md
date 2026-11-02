# Interactive overnight skills

## Intended behavior

Running `token_maxxxer` in a terminal opens a repository picker. It combines
recently selected local paths, configured repositories, the current repository,
and a bounded discovery of nearby projects. A user can enter another local path
or a `file://` URL. Remote URLs are not cloned. History stores canonical local
paths and suggests existing entries first.

The picker then offers repository and user-installed `SKILL.md` files and built-in
code review/improvement skills. Suggestions use local metadata, not an API call.
Users can select a skill explicitly. Skills are instructions for the supported
file tools; installing a skill does not install its external tools or plugins.

`night` also accepts explicit arguments for unattended invocation. A preview
shows the repository, skill, provider/model, mode, limits and verification
commands without retrieving credentials, creating files or calling an API.
Execution requires confirmation or `--yes`. Missing model configuration is
requested interactively; a model is never silently substituted.

## Execution contract

- Claude and OpenAI share the existing provider interface. Copilot remains
  explicitly unsupported. Provider errors stop the session without fallback.
- Review mode exposes bounded, redacted reads of eligible tracked text files.
- Edit mode requires a clean repository and creates a unique branch/worktree
  from the recorded HEAD. All writes stay in that worktree. Git metadata,
  credential files, ignored files, symlinks and paths outside the root are denied.
- A typed JSON action protocol supports file reads, writes, approved verification
  commands and completion. No model-supplied shell command is executed.
- Only verification commands explicitly supplied by the user can execute. Each
  has a timeout and process-group cancellation. A worktree is not an OS sandbox:
  repository code and verification commands must be trusted.
- The skill repeats while it reports remaining useful work, within a wall-clock
  deadline and a maximum API-call count. It stops early when done. No empty work
  is invented to consume tokens. Reported token usage is observed, not a price cap.
- Signals and deadlines stop execution. Session metadata is persisted before
  external effects and after each action. A crashed session is inspectable but
  is never automatically replayed. No durable resume or background service is
  implied by the foreground command.
- Reports preserve the branch/worktree and mark edited work as needing review.
  Nothing is merged, pushed, or automatically committed in a selected repository.

## Acceptance checks

Use temporary Git repositories, simulated providers and a controllable clock.
Cover discovery/history, explicit paths, skill precedence, interactive selection,
network-free previews, isolated edits, denied secrets/symlinks/traversal,
verification failures/timeouts, repeated cycles, deadline/call limits, API
failures, interruption and inspectable session records. No test calls an AI API.
