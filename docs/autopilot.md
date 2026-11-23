# Overnight roadmap autopilot

`autopilot` keeps one or more native Codex agents working until morning. They
implement the open items of the repository's roadmap, milestone by milestone.
When no roadmap item is ready, they fix trusted GitHub issues, then run rotating
maintenance passes: security, tests, coverage, refactoring, relevance, docs and
optionally performance. Every accepted change is verified and committed to a
local review branch. Nothing is pushed or merged.

## How a night runs

1. **Start.** The job starts inside its daily window (`daily_at`, plus
   `latest_start_minutes`) or immediately for a manual `run`. Each date is
   attempted once; a marker prevents replay after a crash or failure.
2. **Plan.** The supervisor reads the roadmap committed at the source `HEAD`.
   It also reads private progress from earlier nights and, if configured,
   lists trusted open issues.
3. **Lanes.** Each agent gets its own branch,
   `token_maxxxer/autopilot-JOB-AGENT-YYYYMMDD`, and worktree. A lane starts
   from the source `HEAD`. If its previous branch still has unmerged commits
   and the source has not moved, the lane continues from that branch instead.
   Approved checks must pass on this baseline before any agent runs.
4. **Cycles.** A LangGraph loop per lane runs four steps: select, execute,
   verify and record. Lanes never share an item. An agent receives one task,
   the repository rules, the protected paths and the checks the supervisor
   will run. It must end with an `AUTOPILOT_RESULT` line. Its status is
   `done`, `partial`, `blocked` or `no_change`.
5. **Verification.** The supervisor stages the agent's changes and rejects:
   - edits to protected paths, including the roadmap;
   - paths outside `write_paths`;
   - credential-like files, symlinks, submodules and files over 2 MiB;
   - added lines containing provider keys, GitHub tokens, AWS keys or private
     keys;
   - deletions when `allow_deletions` is false.

   Approved checks then run. They must pass without changing the worktree.
6. **Record.** Verified work becomes one Conventional Commit:
   - `feat` for roadmap items;
   - `fix` for issues, with `Refs #N`;
   - `test`, `refactor`, `docs`, `perf` or `fix` for maintenance passes.

   When the agent reports `done`, the supervisor checks off the roadmap item
   in the same commit. Rejected work is saved as a private patch in the
   night's directory, and the worktree is reset so the lane can continue.
7. **Stop.** The night ends at the next local `stop_at`, after `max_hours`, or
   when no work is left. Lanes do not start a cycle with less than
   `minimum_task_seconds` left. An agent's time limit leaves one check
   timeout for verification. SIGTERM or the deadline stops every agent's
   process group. Interrupted work stays in its worktree.

## Work sources

**Roadmap.** Markdown headings delimit milestones. Checkbox list items (`- [ ]`,
`* [ ]`, `1. [ ]`) are work items. Indented text under an item becomes its
details. Open nested sub-items run before their parent. Fenced code blocks are
ignored. Each item has a key derived from its milestone, parent and wording, so
a reworded item counts as new work. Without `roadmap_file`, the supervisor looks
for `ROADMAP.md`, `docs/roadmap.md`, `docs/ROADMAP.md` and `roadmap.md`. A
missing roadmap leaves the other sources running.

**Issues.** The supervisor lists open issues of the `origin` GitHub repository
through an authenticated `gh` CLI. Only issues with every configured label and
a trusted author are kept, oldest first. A filter is mandatory: issue text
reaches an agent that has shell access. The prompt marks issue bodies as
untrusted data, but that does not make a hostile issue safe. Restrict labels to
maintainers. Commits reference issues and do not close them. If GitHub is
unreachable, the night continues with its other sources.

**Maintenance.** Focuses rotate across nights. A pass makes at most one
evidenced improvement or reports `no_change`. Maintenance stops for the night
after a full rotation without a commit, so the agents do not invent work to
spend tokens.

## Retries and progress

`progress.json` in the state directory records each roadmap item and issue:

| Status | Meaning |
| --- | --- |
| `done` | Committed with `done` status. The item is skipped while its commit is merged or still on its branch. |
| `partial` | Useful progress was committed. The same lane may continue tonight; the next night's prompt points to the earlier branch. |
| `failed` | The work was rejected or checks failed. The item is not retried the same night. |
| `blocked` / `open` | The agent made no change. A `blocked` item needs a human decision. |

Every outcome counts toward `max_attempts` except agent failures and
interruptions. Agent failures can come from quota or network problems. After
`max_consecutive_failures` failed cycles, the lane stops. If you delete a
branch without merging it, its `done` items reopen on the next night. Edit
the roadmap wording, or remove an entry from `progress.json`, to retry an item
that has used all its attempts.

## Configure and run

Copy [the example](../examples/autopilot.yaml) to a private location outside
the target repository and replace its paths. Use absolute executables in
`verification_commands`; arguments are passed without a shell. Give at most four
agents. A lane can restrict its `sources`, for example to keep one agent on
maintenance while another follows the roadmap.

```bash
uv run token_maxxxer autopilot run --job-file /private/path/night.yaml --dry-run
uv run token_maxxxer autopilot run --job-file /private/path/night.yaml
uv run token_maxxxer autopilot status --job-file /private/path/night.yaml
```

A dry run prints the deadline, lanes and upcoming roadmap items. It does not
write files, call a model or contact GitHub. A manual run consumes that date's
attempt. Exit codes are `0` for a completed night, `1` when the night fails (for
example, every lane failed its baseline checks) and `130` after an
interruption.

Install the daily schedule like a [headless job](headless-skill-jobs.md):

```bash
uv run token_maxxxer autopilot launchd install --job-file /private/path/night.yaml
uv run token_maxxxer autopilot cron install --job-file /private/path/night.yaml
```

The LaunchAgent label is `com.token-maxxxer.autopilot.NAME`. The cron marker is
`token_maxxxer:autopilot:NAME`. Both preserve other jobs and check the window
every minute. The scheduler `PATH` includes the installing Python, Codex, `gh`,
`git`, `uv` and the check executables. Keep the machine awake during the
window.

## Review in the morning

Each night writes to `STATE/runs/YYYY-MM-DD/`:

```text
night.json            # lanes, cycles, outcomes, check results, commits
report.md             # morning summary: branches, cycles and work needing attention
AGENT/cycle-NNN.patch # rejected or failed work, mode 0600
AGENT/worktree/       # kept only when interrupted or not clean
```

Review each branch with `git log` and `git diff`, run the checks, then merge
what you accept. Agent summaries appear in commit bodies after credential
redaction. Treat them as claims to verify. Patches can be applied with
`git apply` for inspection.

## Trust boundaries

- Codex runs with the `workspace-write` sandbox, live web search and no
  interactive approvals. Apps, plugins, hooks and multi-agent features are
  disabled. Path rules are post-execution acceptance checks, not an operating
  system sandbox. Trust the repository and its checks.
- Supervisor Git commands disable hooks and commit signing. Commits use the
  repository's configured identity.
- The supervisor never pushes, opens pull requests, closes issues or merges.
- Parallel lanes can produce conflicting branches. Merge them one at a time.
- The night's deadline is an elapsed-time limit, not a token or monetary
  budget. Each cycle is a full agent session.
