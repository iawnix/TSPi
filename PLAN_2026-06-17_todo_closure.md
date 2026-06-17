# 2026-06-17 TODO Closure Plan

## Scope

This maintenance pass addresses the unresolved feedback recorded in
`/home/iaw/TS/.codex/TODO.md` without changing any scientific result from the
existing TS-search workspaces.

## Objectives

1. Backtrack replacement safety
   - Keep the existing validator warning for replacement branches that lack a
     canonical `backtrack_events[]` record.
   - Add a CLI affordance so a prepared replacement branch can record its
     `record-backtrack --new-branch-node` link in the same command.
   - Add tests covering the new CLI path and the existing validator warning.

2. Explorer workspace selection
   - Stop treating a server-side default workspace as the durable current view
     in multi-workspace mode.
   - Keep single-source compatibility.
   - Move multi-workspace current selection to URL `?workspace=` and browser
     `localStorage`.
   - Ensure unscoped legacy API routes return `workspace_required` when several
     workspaces are registered.

3. Remote execution and Python 3.8 boundary
   - Do not downgrade the whole control-plane package to Python 3.8.
   - Document that remote ASE/xTB execution must use a small engine wrapper or
     py38-compatible subset, while local/control code may stay on the current
     Python baseline.
   - Add a compatibility guard or regression note where the current
     compute-0-21 failure can be caught before a long job is submitted.

4. Remote runner architecture
   - Preserve `run_remote_gaussian.py` as the supported Gaussian entrypoint.
   - Document the next refactor boundary: generic job lifecycle in
     `remote/job_runner.py`, engine adapters for Gaussian/xTB/ASE-NEB, and
     a future `ts_remote_job.py <engine>` CLI.
   - Avoid a large mechanical rewrite in this pass unless tests show the
     current code is already structured for it.

## Validation

- Targeted pytest for backtrack, explorer server, remote Gaussian, and
  architecture tests.
- `py_compile`/import validation with `PYTHONDONTWRITEBYTECODE=1` and
  `PYTHONPYCACHEPREFIX=/tmp/...`.
- Sync the authored checkout to `~/.codex/skills/transition-state-workflow`
  after validation, then re-run the same narrow validation against the installed
  tree.

## Handoff

- Commit and push the authored checkout to `origin/main`.
- Only mark `/home/iaw/TS/.codex/TODO.md` entries complete when the code,
  docs, tests, installed skill, and push are all verified.
