# One supervised night

The ordinary `night` command runs immediately in the foreground. For a single
future window, a checkout includes the tested helper
[`examples/run_night_once.py`](../examples/run_night_once.py). It accepts a private
JSON request, resolves the configured credential while the user is present,
keeps it in memory, waits until the chosen start, then calls the existing night
runner. It never writes the credential to its request, status, logs or environment.
This helper is not included in an installed wheel; use it from this checkout.

The request contains:

- `schema_version: 1` and the validated `NightPlan` as `plan`;
- absolute `skill_file`, `env_file` and `state_directory` paths;
- timezone-aware `starts_at` and `ends_at`, at most 24 hours apart;
- the exact `base_commit` expected at the selected source checkout;
- optional `keep_awake: true`, supported on macOS through `caffeinate`.

The request and its parent directory must stay outside the selected repository.
Keep them private. A permanent `attempted` marker prevents supervisor restarts
from replaying the request, including a failed authorization attempt. An atomic
`status.json` records authorization, waiting, execution and final outcome without
prompts or credentials. A late wakeup shortens the run to the absolute closing
time; a job starting after that time exits without provider access. Source HEAD
is checked before authorization and again after waiting. Changed work is retained
by the normal runner for review.

```bash
/absolute/path/to/token_maxxxer/.venv/bin/python \
  /absolute/path/to/token_maxxxer/examples/run_night_once.py \
  --request-file /private/path/to/launch/request.json
```

On macOS, a one-off `launchd` job can use that argument array with `RunAtLoad`
and `LaunchOnlyOnce` true, `KeepAlive` false, private log paths and a `0077` umask.
Bootstrap it in the logged-in user's GUI domain, then verify `status.json` reaches
`scheduled`; merely writing or loading a plist does not establish successful
authorization. The helper allows 120 seconds for the initial Keychain approval;
ordinary `query`/`night` calls keep their ten-second timeout. No additional
Keychain read is needed when the execution window opens.

The job begins waiting immediately and does not depend on an open terminal.
`keep_awake` prevents idle sleep for its lifetime; it does not override a closed
laptop lid or shutdown. Keep the computer powered and open.

Use `launchctl bootout gui/UID/LABEL` to cancel the registered job. The helper
handles termination and records cancellation; the normal runner retains any
interrupted work. It does not survive logout/reboot or replay work after a
crash. Those behaviors need the future durable workflow and service milestones.
Loading a job from a private request directory does not install a login service.

## When Keychain does not show an authorization dialog

A credential timeout does not prove that macOS displayed a dialog. Do not keep
restarting background jobs on that assumption. For a fresh, unattempted request,
the helper provides an explicit local terminal input path:

```bash
/absolute/path/to/token_maxxxer/.venv/bin/python \
  /absolute/path/to/token_maxxxer/examples/run_night_once.py \
  --request-file /private/path/to/fresh-launch/request.json --prompt-key --detach
```

Type or paste the selected provider's API key only into that terminal prompt.
Echo is disabled; if masked input is unavailable, the helper refuses to read it.
The value is validated without changing the process environment or `.env`.
It travels through an inherited anonymous pipe to a detached worker, stays in
memory there, and is never placed in argv, environment variables, files or logs.
The worker skips Keychain retrieval and runs the same bounded, non-replaying plan.
The terminal can close once the worker is confirmed ready.

`waiting_for_local_key` means input is still needed. A printed worker PID means
only that the process was launched: inspect `status.json` for `scheduled` or
`running` before declaring readiness. `worker.log` contains only safe diagnostics.
Cancel a waiting prompt with Ctrl+C. An expired or previously attempted request
is rejected before prompting. A detached process does not survive logout/reboot.
An interrupted or failed handoff terminates and reaps its worker. Once the
handoff completes, closing the input terminal leaves the worker running;
inspect its recorded PID/status and send SIGTERM to stop it explicitly.

## Knowledge vault pilot

The example skill
[`knowledge-vault-maintenance`](../examples/skills/knowledge-vault-maintenance/SKILL.md)
reviews note consistency and reciprocal internal links. Its supporting conventions
fit the file-tool limit even when the vault README exceeds 64 KiB. It preserves
French content, card IDs and review dates; it does not conduct interactive
interviews or invent new technical facts.

For `Knowledge_AI_Engineering`, prepare a separate clean checkout from the chosen
published commit when the existing clone has uncommitted work. Record that commit
and preserve the original clone. Install its verification dependencies in a
separate private environment and run `make check` there before authorizing the
same check for the night session. Freeze the skill/resources and launcher copies
used by an already registered job rather than modifying them during the wait.

Tests cover authorization before waiting, the closing deadline, late wakeup,
source changes, cancellation, secret-free failure records and no duplicate
attempts. They use simulated providers. Operational authentication and pilot
evidence, when actually obtained, belong in [checkpoint.md](checkpoint.md).
