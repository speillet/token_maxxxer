# Roadmap — token_maxxxer

Updated November 7, 2026. `token_maxxxer` supports Claude/OpenAI APIs, Codex CLI
login and the optional official Copilot SDK. Explicit fallback chains preserve
context and session limits across exhausted provider allocations.
Progress, merge history, and rollback points live in [checkpoint.md](checkpoint.md).

## 0 — Provider contracts and account access

- [x] Document official Claude Messages and OpenAI Responses integrations.
- [x] Define a provider-independent interface and normalized generation results.
- [x] Add private credential references and network-free diagnostics.
- [ ] Qualify real accounts using renewed credentials and authorized models.
- [ ] Qualify Copilot SDK authentication, GitHub tokens, and account permissions.

Simulated transports allow development without billed calls. They do not prove
real account permissions, quotas, or costs.

## 1 — Python foundation

- [x] Name the package, command, imports, and examples `token_maxxxer`.
- [x] Lock dependencies and validate configuration and domain models.
- [x] Import tasks atomically and idempotently, ordered by priority then arrival.
- [x] Version the initial SQLite schema and separate future checkpoint locations.
- [x] Provide read-only diagnostics, task listing, and selection previews.
- [x] Run Ruff, strict typing, tests, and macOS/Linux CI.
- [x] Remove the retired CLI implementation and dependencies that are not used.
- [x] Maintain repository documentation, messages, examples, and test data in English.

## 2 — API generation adapters

- [x] Claude: official SDK, API keys, text prompts, and usage observations.
- [x] OpenAI: official Responses SDK with response storage disabled in the request.
- [x] An explicit query command without local code execution or task mutations.
- [x] API HTTP timeouts, output-token limits, and no automatic SDK retries.
- [x] Classify authentication, quota, timeout, network, and incomplete-output failures.
- [x] Resolve private Keychain references or process keys only when needed.
- [x] Test simulated HTTP without real AI API calls.
- [x] Add Codex CLI and optional GitHub Copilot SDK text adapters.
- [x] Add explicitly authorized quota fallback with shared call/deadline limits.

A completed generation does not verify a development task. Model settings are
explicit. Switching is limited to an explicitly authorized fallback chain.

## 3 — Code agent, Git isolation, and verification

- [x] Build the provider-backed loop for typed file tools in foreground night sessions.
- [x] Restrict reads/writes and expose only user-approved verification commands.
- [ ] Prepare a stable task branch and worktree from an explicit Git base.
- [x] Isolate night sessions from the original working tree with unique branches/worktrees.
- [x] Run approved verification with timeouts, bounded logs and process-group cleanup.
- [x] Retain night-session worktrees, failures and unverified changes for review.
- [ ] Use needs_review for human acceptance criteria; never merge automatically.
- [ ] Connect run --once only after these controls and a reversible pilot.

### Interactive overnight CLI

- [x] Pick a discovered local repository or enter a local path/file URL.
- [x] Suggest recent canonical paths from private local history.
- [x] Discover repository/user SKILL.md instructions and offer built-in skills.
- [x] Support explicit skill selection and deterministic local suggestions.
- [x] Repeat useful skill cycles within a duration and API-call ceiling.
- [x] Preview without credential resolution, API access or file creation.
- [x] Persist session records and reports; inspect active or interrupted sessions.
- [x] Stop on deadline, signals, call limit, completion or provider failure.

`night` starts immediately in the foreground and marks edited work as needing
review. Its default delivery stays local; `improve` and `night --publish-pr`
explicitly enable supervised commit/push/draft-PR delivery. Nothing merges
automatically. The
original queue's stable task branches and acceptance workflow remain separate
work. Skills use the supported typed tools; external plugins and arbitrary shell
commands are not installed or executed. See [the session contract](night-cli.md).

## 4 — Durable workflow and recovery

- [ ] Install LangGraph, LangChain Core, and the compatible checkpointer when implementing this milestone.
- [ ] Add deterministic selection, preparation, execution, verification, classification, and reporting nodes.
- [ ] Use a SQLite checkpointer, stable thread IDs, and a versioned state schema.
- [ ] Journal attempts before external effects and persist results immediately.
- [ ] Add atomic acquisition, a local service lock, and pause/resume/cancel commands.
- [ ] Pause expired authentication and require review of ambiguous executions.
- [ ] Test crashes before launch, during work, and after results; observe no duplicate launches.

Foreground night sessions already journal API attempts and approved checks,
use a per-repository lock, and preserve interrupted work. They do not implement
workflow replay, durable resume or automatic crash recovery.

## 5 — Scheduling, quota handling, and budgets

- [ ] Implement half-open IANA windows, midnight crossing, overlap merging, and DST.
- [ ] Check before launch and maintain a watchdog through closing, including shutdown grace.
- [ ] Pause on quota with a reliable reset or bounded backoff, never rapid retries.
- [ ] Persist next_retry_at and counters across restarts.
- [ ] Configure active-time and API budgets with explicit cost uncertainty.
- [ ] Handle supervisor signals and terminate owned subprocess groups.

## 6 — Services and reports

A tested one-shot helper can already hold an explicitly resolved credential
in memory, wait for a single absolute window and run under a local supervisor.
It prevents replay and reports readiness; the macOS pilot uses a private
`launchd` job. Recurring service installation and durable recovery remain open.
See [one supervised night](one-shot-night.md).

- [ ] Add user launchd and systemd services with explicit environments.
- [ ] Resolve credentials without silent background authentication prompts.
- [ ] Support clean installation, start, stop, inspection, and removal.
- [ ] Produce Markdown reports and rotating JSONL logs with secret checks.
- [ ] Document sleep/wake behavior and retain all unverified work.

## 7 — Pilot and version 0.1

- [ ] Run a simple task in a demonstration repository, then a short scheduled window.
- [ ] Run independent tasks covering success, failed verification, and recovery.
- [ ] Simulate quota, network, expired authentication, service restarts, and sleep/wake.
- [ ] Validate macOS/Linux, verifiable results, no observed duplication, and explained consumption.
- [ ] Publish a local 0.1 release only after the complete MVP is validated.

## After the MVP

- [ ] Import explicitly selected GitHub issues with deduplication and dependencies.
- [ ] Estimate task size and select work that fits the available window.
- [ ] Add a local dashboard and reserve estimates with stated uncertainty.
- [ ] Optionally create PRs from verified results.
- [ ] Add concurrency only after measuring its value and resolving Git conflicts.
