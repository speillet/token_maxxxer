# Daily headless skill jobs

`headless run` uses a LangGraph workflow to prepare a persistent review worktree,
establish the baseline, invoke native Codex, verify the result and commit valid
changes locally. Native Codex can read large notes, run the skill's scripts and
consult sources through web search and configured MCP servers such as Context7.
It uses the existing Codex login and an explicit model.

## Configure a job

Copy [the example](../examples/headless-review.yaml) into a private YAML file
outside the target repository. Set absolute paths for the repository, its
committed `SKILL.md`, an external state directory, the Codex executable and any
tools required by the verification commands. List the subjects in the desired
review order. Each successful run advances to the next subject; the list wraps
after its last entry.

For `Knowledge_Computer_Vision`, use `.agents/skills/revue-cartes/SKILL.md` in
default deepen mode. Supply its card files as subjects, `vault/**/*.md` and
`docs/revues/*.md` as permitted write patterns, and these checks:

```text
python scripts/check_vault.py
python scripts/sync_catalog.py --check
python scripts/learning_path.py
uv run --no-project --with genanki==0.13.1 python -m unittest discover -s tests
python .agents/skills/revue-cartes/scripts/inventaire_cartes.py vault --compare {inventory_before}
```

Use the same Python environment with `genanki==0.13.1` for the inventory and
checks. `inventory_command` must emit a JSON inventory on stdout. The supervisor
saves it privately before execution; `{inventory_before}` in command arguments
is replaced with that file's absolute path. Arguments are passed directly,
without a shell. Checks run before and after the agent and must all pass.

```bash
uv run token_maxxxer headless run --job-file /private/path/job.yaml --dry-run
uv run token_maxxxer headless run --job-file /private/path/job.yaml
```

Running manually consumes that day's attempt. Dry runs make no model request
and create no files. Automated tests use a simulated Codex executable.

## Install daily execution

On macOS, use a user LaunchAgent:

```bash
uv run token_maxxxer headless launchd install --job-file /private/path/job.yaml
uv run token_maxxxer headless launchd status --job-file /private/path/job.yaml
uv run token_maxxxer headless launchd remove --job-file /private/path/job.yaml
```

The job is loaded in the logged-in user's GUI domain and stays available across
terminal closures and later logins. It checks immediately and once per minute,
using the same timezone and attempt guards. Logs go to `scheduler.log`.
An installation failure restores the previous LaunchAgent. The installing
Python interpreter must remain available; a stable wheel-based virtualenv is
recommended. macOS may reject crontab writes with `Operation not permitted`;
the LaunchAgent does not require changing that permission.

On systems supporting user cron:

```bash
uv run token_maxxxer headless cron install --job-file /private/path/job.yaml
uv run token_maxxxer headless cron status --job-file /private/path/job.yaml
uv run token_maxxxer headless cron remove --job-file /private/path/job.yaml
```

The marked cron block preserves unrelated entries and backs up the prior
crontab privately. It captures the installing Python interpreter and tool PATH;
install from a stable virtualenv containing the built wheel for long-lived jobs.
No terminal needs to stay open. The machine must be awake for cron to launch it.

Cron checks once per minute. Python starts the actual agent once per local date,
within `latest_start_minutes` after `daily_at` in the configured IANA timezone.
This avoids depending on host cron timezone support. The default is 22:00
Europe/Paris, with a one-hour start window. A wakeup inside that window can still
start the job; a missed window is skipped. An exclusive attempt marker prevents
replay after a crash or failure, including the repeated hour at the autumn DST
transition. A total deadline and per-check deadlines stop owned subprocesses.
The total deadline is an elapsed-time limit, not a token or monetary budget.

## Inspect the results

State is stored under the configured `state_directory`:

```text
worktree/                         # persistent local review branch
progress.json                     # next subject after successful verification
last-tick.json                    # most recent actual invocation by the scheduler
runs/YYYY-MM-DD/attempted          # exclusive no-replay marker
runs/YYYY-MM-DD/status.json        # phases, subject, checks, changed files, commit
runs/YYYY-MM-DD/inventory-before.json
runs/YYYY-MM-DD/inventory-after.json
cron.log                          # compact results and launch errors
scheduler.log                     # corresponding LaunchAgent log on macOS
```

Changes accumulate on `token_maxxxer/headless-JOB_NAME`. The original checkout
is preserved, including uncommitted work. Nothing is pushed or merged. Inspect
the review worktree's log and compare its branch to the source branch. The skill
also writes subject reports under `docs/revues/`.

Codex runs with the `workspace-write` sandbox, live web search and no interactive
approvals. Configured MCP servers remain available; apps, plugins, hooks and
subagents are disabled. The native runtime has shell tools, unlike the bounded
text-action adapters. Trust the selected repository, skill and approved checks.
The write patterns are a post-execution acceptance check, not an OS sandbox.
The supervisor rejects deletions, unexpected branch or HEAD changes and edits
outside those patterns before committing. The card inventory comparison also
rejects changed Anki identities. New-card proposals remain pending for the
learner; unattended enrichment does not authorize adding cards.

If a run fails, its attempt is retained and its subject does not advance. Dirty
or unverified work stays in the review worktree and blocks subsequent execution
until inspected. Stop scheduling before resolving that work; do not erase an
attempt marker to replay an ambiguous run. A clean review branch may fast-forward
to the source HEAD. If source and review branches diverge, the job stops for
manual integration rather than merging them automatically. LangGraph has no
durable checkpointer here: automatic resume and crash replay remain unimplemented.
