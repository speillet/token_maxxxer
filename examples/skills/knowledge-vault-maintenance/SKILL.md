---
name: knowledge-vault-maintenance
description: Improve the consistency and internal links of an Obsidian flashcard vault using bounded file tools and approved checks, without interactive questions.
---

# Maintain a knowledge vault

Work autonomously on note consistency and internal navigation. Preserve the
vault's language: Knowledge_AI_Engineering uses French. Use the available typed
file tools and approved checks only. Do not require an interview, a browser,
external plugins, shell access, or subagents.

## Establish the conventions

Read `vault-conventions.md` with `read_skill_file`. Then inspect the root MOC,
the relevant notes and their reciprocal connections with `read_file`.
The reference repository's README exceeds the 64 KiB file-tool limit; use the
supporting conventions instead of repeatedly requesting that oversized file.
Load applicable AGENTS.md instructions when available. If approved checks exist,
run them to identify concrete structural or linking problems before editing.

## Make focused corrections

- Prioritize broken links, missing reciprocal connections, inconsistent names,
  unclear cross-references and questions that cannot be understood in isolation.
- Read the destination note before adding a connection. Explain why it belongs,
  add the reciprocal connection, and keep the MOC link last.
- Preserve filenames, card meaning, Anki IDs, Spaced Repetition comments, tags,
  summary comments, section order and existing verification dates.
- Keep existing card boundaries. Do not create or remove cards, rename notes,
  change technical claims, invent sources, or renew verification dates.
- Limit writes to existing note Markdown and editorial Markdown under `docs/`.
  Do not change scripts, tests, dependency files, CI, skills or private settings.
- Leave generated README/MOC catalog blocks unchanged. Changes to card counts,
  titles or summaries need catalog generation and are outside this session's scope.
- Prefer a small coherent group of corrections, with evidence, over cosmetic
  rewrites or changes made only to keep the session busy.
- Prefer notes below 20 KiB so their full replacement fits one response. Never
  truncate a note to fit an output limit; report the finding if a safe full edit
  cannot be returned.

## Verify and report

Run the approved checks after each group of edits. Use their actual output to
correct regressions; never weaken a check or claim it passed without execution.
If a pre-existing failure cannot be corrected within the allowed note scope,
report it with the affected files and stop rather than editing the tooling.

Finish each cycle with a French summary identifying the files, the problem,
the correction and the observed check results. Report partial coverage honestly.
Set `continue_work` to true only when a specific useful unreviewed area remains.
Otherwise finish: do not invent work to consume API calls. Changes remain in an
isolated worktree for human review, without commits, push or automatic merge.
