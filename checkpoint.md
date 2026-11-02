# Checkpoints — token_maxxxer

Updated November 2, 2026. This file records code deliveries, validation, merge
history, and rollback points. It does not replace future workflow checkpoints.

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
| 3–7 | Planned | Code-editing tools, worktrees, durable workflow, scheduling, services |

Text generation does not verify or complete a Git task. Tests use fictional
credentials and simulated HTTP without billed calls. Repository documentation,
messages, examples, and test descriptions are maintained in English.

## Integration ledger

| PR | Role | Decision |
| --- | --- | --- |
| [#1](https://github.com/speillet/token_maxxxer/pull/1) | Python foundation and persistent task queue | Merged into main as `2b38985`; four CI checks passed after retrying a cancelled job |
| [#2](https://github.com/speillet/token_maxxxer/pull/2) | Retired subscription CLI prototype | Closed as superseded; shared work preserved through #3 |
| [#3](https://github.com/speillet/token_maxxxer/pull/3) | Current name and Claude/OpenAI API providers | Retargeted to main and merged as `f7f5fb2`; four CI checks passed |
| [#4](https://github.com/speillet/token_maxxxer/pull/4) | Remove dead code and unused dependencies; translate maintained content | Cleanup delivery; integration status and merge commit are available on the linked PR |

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
| CP-027 | `feat(cli): add interactive overnight sessions and inspection` | No-argument picker, explicit night/repository/skill/session commands, confirmed API use, provider profile and network-free previews; 191 tests pass locally |

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
3. Implement typed code tools, approved worktrees and verification before run --once.
4. Add the Copilot SDK adapter with explicit GitHub authentication.
5. Install and implement the durable workflow, pauses, scheduling and services at their milestones.
