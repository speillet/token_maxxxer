# Checkpoints — token_maxxxer

Updated November 3, 2026. This file records code deliveries, validation, merge
history, and rollback points. It does not replace future workflow checkpoints.

## November 3 supervised pilot

The requested target is `speillet/Knowledge_AI_Engineering`, with note consistency
and internal links as the selected goal. Its dirty original clone is preserved.
A separate clean source worktree is pinned to published commit
`218570fa71cf0af0f977f82b6466c3f6900035f7`; its full `make check` passes with
147 notes, zero structural warnings/errors and 54 tests. The maintenance skill
preserves French, card IDs and verification dates, without inventing new claims.

The prepared window is November 3 at 22:00 through November 4 at 07:00 in
Europe/Paris, at most 100 calls, with Claude Sonnet 5.5 and approved `make check`.
Private copies of the request, helper, skill/resources, a lockfile-pinned runtime
and the verification environment are outside the target repository. Existing
`.env` and Keychain entries are unchanged; no plaintext credential is written.

The real Claude model-list endpoint authenticated successfully and exposed the
configured model. This is not proof of inference quota or a completed pilot.
The first supervised launch reached `authorizing`, then failed before execution
when its two-minute native Keychain authorization expired. No model-generation
request or target edit was made by that job. A further launch must use a fresh
explicit attempt and be observed in `scheduled` state before claiming readiness;
the permanent attempt marker must not be cleared for automatic replay.

Implementation validation: 229 simulated tests pass; Ruff, strict mypy and
source/wheel builds pass. All four macOS/Linux checks at `38c2009` pass in
[CI run 41633836332](https://github.com/speillet/token_maxxxer/actions/runs/41633836332).
Standards and Spec rereviews report zero open findings after absolute-deadline
and secret-safe reporting corrections. The one-shot helper does not implement
recurring schedules, login persistence, durable replay or a production service.

### Missing-dialog follow-up

The next supervised attempt and a foreground Terminal attempt also failed to
read the credential. The login keychain was observed unlocked, and no visible
authorization dialog was confirmed. A timeout must not be described as proof
that a dialog is displayed or that the key is accessible in the background.

PR #7 adds an explicit masked local-input path. A fresh Terminal launcher was
observed on a real TTY with `waiting_for_local_key`: it had not received a key,
created an attempt marker or started inference. After local entry, the value
travels only through an anonymous pipe to the detached worker. Readiness still
requires observing `scheduled` or `running`, not merely a PID or open window.

Both review axes are clear after correcting pre-prompt repository validation
and interrupted-worker cleanup. The 239-test suite passes on Python 3.11 and
3.13, including a real child-process handoff that deliberately rejects Copilot
before network access. Existing `.env`/Keychain data and target worktrees remain
unchanged. Private frozen helpers and request files are outside the repository.

## Current direction

The repository, package, and command are named `token_maxxxer`. Claude and OpenAI
use explicit API credentials through `Provider`; Copilot will use its official
SDK and authorized GitHub credentials. The original subscription-only CLI design
has been retired. Historical implementations remain available in Git.

| Milestone | Status | Evidence and remaining work |
| --- | --- | --- |
| 0 — Provider contracts | Defined; real-account pilot open | Official API contracts and simulated tests; no real account calls |
| 1 — Python foundation | Delivered | Validated configuration, models, SQLite imports, diagnostics, previews |
| 2 — API generation | Implemented | Claude/OpenAI adapters; Copilot not yet implemented |
| 3 — Code tools and isolation | Partly implemented | Foreground night sessions, typed tools, worktrees and approved checks; imported-task execution remains gated |
| Interactive overnight CLI | Implemented | Local discovery/history, skill picker, bounded cycles and private reports; simulated providers only |
| 4–7 | Planned | Durable workflow/recovery, schedule windows, services and real-account pilots |

Text generation does not verify or complete a Git task. Tests use fictional
credentials and simulated HTTP without billed calls. Repository documentation,
messages, examples, and test descriptions are maintained in English.

## Integration ledger

| PR | Role | Decision |
| --- | --- | --- |
| [#1](https://github.com/speillet/token_maxxxer/pull/1) | Python foundation and persistent task queue | Merged into main as `2b38985`; four CI checks passed after retrying a cancelled job |
| [#2](https://github.com/speillet/token_maxxxer/pull/2) | Retired subscription CLI prototype | Closed as superseded; shared work preserved through #3 |
| [#3](https://github.com/speillet/token_maxxxer/pull/3) | Current name and Claude/OpenAI API providers | Retargeted to main and merged as `f7f5fb2`; four CI checks passed |
| [#4](https://github.com/speillet/token_maxxxer/pull/4) | Remove dead code and unused dependencies; translate maintained content | Merged into main as `c72dd91` |
| [#5](https://github.com/speillet/token_maxxxer/pull/5) | Interactive repository/skill selection and isolated overnight sessions | Feature delivery; current review/CI status is available on the linked PR |
| [#6](https://github.com/speillet/token_maxxxer/pull/6) | Supervised one-shot launcher and knowledge-vault maintenance skill | Current delivery and integration status are available on the linked PR |
| [#7](https://github.com/speillet/token_maxxxer/pull/7) | Masked local credential input and detached in-memory handoff | Current delivery and integration status are available on the linked PR |

The cleanup branch starts at `fc0a7c3`. It removes the old CLI adapter, its
subprocess transport and authentication constants, terminal wire parser, fake
CLI, obsolete fixtures/tests, and archived CLI contract. Shared redaction and
API coverage remain. LangGraph, LangChain Core, and the graph SQLite checkpointer
are deferred until their milestone is implemented.

The API result is now `GenerationResult` in `results.py`. `response_id` replaces
`session_id`; unused `exit_code`, `stdout`, and `stderr` fields are removed.
The SQLite application ID and schema are unchanged, and local credentials and
databases are preserved. After cleanup, 125 relevant tests pass locally; removed
prototype tests account for the lower count compared with the earlier 211-test suite.
The retained suite passes under Python 3.11 and 3.13. Ruff, strict typing and
package builds pass, and all four macOS/Linux CI jobs at `0cc208d` succeeded.
Standards and Spec reviews reported no findings. Branches are removed only after
their heads are confirmed to be ancestors of main; rollback commits remain reachable.

## Rollback points

| Checkpoint | Revision | Scope and evidence |
| --- | --- | --- |
| CP-000 | `ad0992b` | Original README and roadmap; clean working tree before implementation |
| CP-001 | `0fdce5a` | Initial external CLI contract and checkpoint protocol |
| CP-002 | `26469a7` | Locked Python foundation, safe YAML, configuration and models; 31 targeted tests |
| CP-003 | `dbcb978` | Initial SQLite migration, atomic imports and stable queue ordering; 9 queue tests |
| CP-004 | `9dcefaf` | Initial diagnostics, imports, listing and previews; 50 total tests |
| CP-005 | `425075f` | macOS/Linux CI with Python 3.11/3.13 and SHA-pinned actions |
| CP-006 | `e3f7f88` | Reject nested SQLite paths and file parents; 55 tests |
| CP-007 | `ae1ecf7` | Documented foundation, head of PR #1 |
| CP-008 | `552e051` | Historical terminal-result normalization and redaction |
| CP-009 | `ecb3b67` | Historical bounded subprocess transport; requires CP-011 macOS fix |
| CP-010 | `819261c` | Historical qualified CLI adapter and deterministic fake |
| CP-011 | `f352270` | Historical macOS process-group cleanup fix |
| CP-012 | `3cba885` | Escaped JSON redaction, strict result fields and interrupted-output checks |
| CP-013 | `7195818` | Duplicate JSON and multiline credential redaction; 156 tests |
| CP-014 | `0342492` | Private credential reference convention and secret-free example |
| CP-015 | `f887f88` | Final PR #2 head, before API-provider requirements |
| CP-016 | `48ee353` | Rename package, command, imports and examples to token_maxxxer |
| CP-017 | `e923570` | Claude/OpenAI SDK adapters, explicit query and private references; 194 tests |
| CP-018 | `9b010df` | Provider selection, reference-path and credential-redaction tests; 201 tests |
| CP-019 | `05bb7c2` | API README, roadmap and provider contract |
| CP-020 | `29a4e7b` | Reject refused/incomplete output items and unsupported tool calls; 207 tests |
| CP-021 | `0d057cc` | Reject oversized prompts before API access and preserve whitespace; 211 tests |
| CP-022 | `fc0a7c3` | Final PR #3 head; four successful macOS/Linux CI jobs |
| CP-023 | `2bbe5a7` | Retire unused code/dependencies and use English application messages; 125 retained tests |
| CP-024 | `0cc208d` | English README, roadmap, provider contract, contribution guide and checkpoint ledger; four successful CI jobs |
| CP-025 | `2f75c84` | Local path/file-URL validation, bounded discovery, private recent-path history, repository/user SKILL.md catalogs and built-in instructions; tested without AI calls |
| CP-026 | `d24eb13` | Typed file tools, signal/deadline cancellation, approved verification, per-repository locking, private session records and reports; original working trees remain untouched |
| CP-027 | `18090c5` | No-argument picker, explicit night/repository/skill/session commands, confirmed API use, provider profile and network-free previews; 191 tests pass locally |
| CP-028 | `165f3fe` | CLI usage, skill/tool scope, foreground limits, reports and review/rollback procedure |
| CP-029 | `c8fa6d4` | Review corrections: reject credential arguments, sanitize records, exclude conventional credential files and linked skill roots, scope repository skill resources to the worktree, atomically replace reports, and defer Git status until confirmed execution |
| CP-030 | `0f7f53d` | Reject split, prefixed, camelCase and environment-assignment credential options before persistence; 211 tests pass on Python 3.11/3.13 and all four macOS/Linux CI jobs pass |
| CP-031 | `8a0a196` | Final operational scope, PR reference, account-independent validation and resolved Standards/Spec reviews |
| CP-032 | `7b829b5` | Credential-name checks apply only to verification options and assignments; positional words such as `pytest -k token` are accepted |
| CP-033 | `f087fc7` | File tools no longer hide tracked `var`/`worktrees` directories copied from this repository's ignore rules |
| CP-034 | `88a4118` | Plan validation, including review mode without checks, lives only in `NightPlan` |
| CP-035 | `345f071` | Local failures record the exception class name without its message; 217 tests pass |
| CP-036 | `docs: move project documentation into docs/` | `README.md`, guide index, and `docs/roadmap.md`/`docs/checkpoint.md`; overnight details moved to `docs/night-cli.md` |
| CP-037 | `f91fabc` | Optional approval timeout up to 300 seconds, with the existing ten-second default preserved and simulated credential coverage |
| CP-038 | `6f5c625` | Tested one-shot helper, no-replay marker, absolute closing deadline, private status and optional macOS idle-sleep inhibition; non-interactive knowledge-vault consistency skill |
| CP-039 | `38c2009` | Absolute closing time also bounds runner preparation and pre-provider journal I/O; error-status failures cannot chain secret-bearing tracebacks; 229 tests and all four CI jobs pass |
| CP-040 | `8eb310c` | Both review axes resolved; published target source and checks pinned; actual launch readiness distinguished from successful model-list authentication |
| CP-041 | `ffe5310` | Explicit TTY-only masked input and anonymous-pipe transfer to a detached worker; Keychain is skipped for the preloaded secret, which is not written to argv, environment, files or logs |
| CP-042 | `bcbfdd7` | Validate request location before prompts/records; interrupted handoffs terminate/reap their worker; a real child-process test verifies pipe transfer without network access; 239 tests pass |

Use `git log --all --oneline` to find the SHA for a checkpoint identified by
commit subject. Earlier checkpoint source is recoverable even after its branch
is removed because the integration preserves commit history.

## Rollback procedure

Inspect an old revision without changing the current working tree:

```bash
git worktree add --detach ../token_maxxxer-cp022 fc0a7c3
```

For a published code rollback, create a branch, run `git revert <sha>` from newest
to oldest for dependent changes, rerun validation, and open a PR. For a merge
commit, inspect its parents and use `git revert -m 1 <merge-sha>` when reverting
the change introduced to main. Do not rewrite shared history.

Git does not restore local `.env` files, Keychain entries, databases, reports,
or unverified worktrees. Back up SQLite through its backup API before future
schema changes, and preserve unverified work separately. The initial migration
has no destructive downgrade. Credential rotation and local cleanup are separate
from source rollback.

## Next work

1. Read the integration ledger and verify the latest main revision before continuing.
2. Qualify real accounts only during an explicitly requested call with renewed credentials.
3. Connect imported tasks to stable worktrees and acceptance verification before run --once.
4. Add the Copilot SDK adapter with explicit GitHub authentication.
5. Install and implement the durable workflow, pauses, scheduling and services at their milestones.

## Overnight CLI delivery

The feature branch starts at `c72dd91`. See [the execution contract](night-cli.md).
The interactive CLI selects a local repository, suggests recent paths, discovers
repository/user skills, and runs the chosen instructions through typed tools.
It supports Claude/OpenAI without changing the existing credential contract.
Edit sessions require a clean repository, lock the common Git directory and
retain a unique worktree/branch from the recorded HEAD. Only explicitly approved
verification argument arrays execute. Work remains uncommitted and needs review.

Session records are written before API requests/worktree preparation/checks and
after results. Duration, call count, tool-denial limits, completion, API errors
and signals stop the foreground loop. Prompts and file contents are not journaled.
Latest cycle summaries/check outputs are bounded and redacted. Interrupted or
ambiguous crash records remain inspectable, without automatic replay.

History, profiles and runs use a separate private state directory, outside the
selected repository; the task-queue schema and local `.env`/Keychain stay intact.
Git source rollback does not remove those records or recover uncommitted edits.
Before removing a run's worktree or branch, inspect `status` (including new files)
and `diff`, commit/back up valuable work and record the session's base commit.

Local simulated-provider validation passes 211 tests under Python 3.11 and 3.13.
Ruff formatting/lint, strict mypy and wheel/source builds pass. CI run
[41535885524](https://github.com/speillet/token_maxxxer/actions/runs/41535885524)
at `0f7f53d` passed all four macOS/Linux jobs. Package audits exclude the local
`.env`, and a network-free CLI preview and documentation-link checks pass.

Standards review initially found credential-bearing command arguments,
conventional credential files, linked skill ancestors and non-atomic reports.
Spec review found ignored skill resource reads and pre-confirmation Git clean
filter execution. All findings have dedicated regression coverage and are fixed;
targeted rereviews report zero remaining findings on either axis.

A follow-up relevance review (CP-032 to CP-035) found that credential-name checks
rejected positional verification words such as `pytest -k token`, and that file
tools hid tracked `var`/`worktrees` directories in other repositories. It also
removed duplicated plan validation and recorded the exception class of local
failures. Each change has regression coverage; 217 tests pass locally. The
project documentation now lives in `docs/`, with a shorter `README.md` index.

Account access, real model compliance and a complete overnight pilot are not
claimed. The CLI is foreground-only: no schedule-window service, durable resume,
arbitrary shell, external skill plugins, automatic commits, push or merge are
implemented.

## Migration from the prototype

Update imports, commands, and configuration to `token_maxxxer`, add `provider`,
and set `authentication.mode` to `api_key`. Credential reference variables use
the `TOKEN_MAXXXER_` prefix. The shared result type is now `GenerationResult`;
`response_id` replaces the misleading `session_id`, and unused subprocess fields
have been removed.

The retired subscription CLI transport, subprocess runner, wire parser, fixtures,
and archived CLI contract have been removed; their history remains available
through the checkpoints above. No local data or Keychain entry is automatically
renamed or deleted. To retain an existing database, keep its explicit path in
`storage.database`; its SQLite application ID and schema remain compatible.
Back up local data separately.
