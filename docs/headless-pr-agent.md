# Headless improvement through pull requests

## Behavior and boundaries

`improve` selects a local repository and runs the existing provider-backed skill
agent without further interaction after confirmation. `--headless` is an alias
for `--yes`; unattended runs supply their repository, model and approved checks.
The interactive picker also offers delivery through a draft pull request.

Publication is explicit: `improve` enables it, and `night --publish-pr` opts in.
At least one approved verification command is required. The remote must identify
a GitHub.com repository; the GitHub CLI must be authenticated with write access.
Previews use local metadata only, without fetching, authentication or API calls.

The supervisor fetches the explicit remote base into a private Git ref and
creates its unique session branch/worktree from that commit. The original
checkout can have uncommitted work; neither its working files nor unpublished
commits are included in the publication branch.

At each completed improvement cycle:

1. Run all approved checks against the final edits.
2. Require a successful check result and no unowned changes in the worktree.
3. Stage only eligible files written by the agent, checking for credentials,
   ignored paths, symlinks, unexpected modes and index changes.
4. Create a Conventional Commit and verify its exact parent/tree after hooks.
5. Push only the session branch with an expected remote-head lease.
6. Create one draft PR or update that session's existing open draft PR.

The model cannot issue Git/GitHub commands. Commit, push and PR creation remain
deterministic supervisor operations. Git identity and hooks follow repository
configuration; commands have timeouts and cancellation. The runner never merges
the target PR. Failed checks, an empty diff, unsafe files, unexpected Git state,
closed PRs and expired deadlines cannot trigger a new publication.

Record local commits, pushed head and PR URL in the private session journal
before/after effects. Preserve local work and classify failures explicitly.
Reconcile ambiguous pushes/PR creation with read-only queries; do not blindly
repeat an uncertain external effect. Existing local-only sessions retain their
current behavior.

## Validation

Use temporary repositories and simulated GitHub/provider operations. Exercise
verified multi-cycle commits, one PR per session, empty changes, failed checks,
dirty original checkouts, unpublished local commits, path/secret/index guards,
remote-ref collisions, interrupted/ambiguous publication, closed PRs and
network-free previews. Automated tests must not open real PRs or call AI APIs.
