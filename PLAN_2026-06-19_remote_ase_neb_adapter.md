# 2026-06-19 Remote ASE-NEB Adapter Plan

## Scope

Close the `/home/iaw/TS/.codex/TODO.md` feedback that ASE/xTB NEB remote
execution still depends on ad hoc shell runners and local installed skill paths.

## Boundary

- Keep `remote/exec.py` as the only local subprocess/SSH argv construction
  boundary.
- Keep `remote/job_runner.py` as the engine-neutral lifecycle boundary:
  directory creation, upload, foreground/background submit, receipt/metadata,
  status/tail/fetch snippets, and downloads.
- Add an ASE-NEB engine adapter that builds `RemoteJobSpec` and invokes the
  existing `scripts/ase_neb_framework.py run <config>` entry point from a
  tool copy staged inside the remote TS-search workspace.
- Add a generic `scripts/ts_remote_job.py` CLI with initial
  `submit/status/tail/fetch --engine ase-neb` support.
- Do not start real compute jobs during validation; use dry-run/mock coverage.

## Implementation Steps

1. Add `remote/ase_neb_runner.py` to resolve node-scoped local/remote paths,
   collect config plus referenced XYZ uploads, stage a minimal tool runtime, and
   build the ASE-NEB `RemoteJobSpec`.
2. Add `remote/job_cli.py` as the generic command router for
   `submit/status/tail/fetch`, initially accepting only `--engine ase-neb`.
3. Add `scripts/ts_remote_job.py` as the thin wrapper that imports
   `transition_state_workflow.remote.job_cli.main`.
4. Ensure dry-run output proves the remote runner uses
   `<remote-root>/tools/transition-state-workflow/scripts/ase_neb_framework.py`
   and never `/home/iaw/.codex/skills/...`.
5. Update `SKILL.md`, `references/candidate_generation.md`, and
   `references/compute_hosts.md` to document the generic remote job CLI and the
   ASE-NEB adapter contract.
6. Add tests covering spec construction, dry-run command text, help output,
   generic status/tail/fetch routing, and absence of local installed skill
   paths in remote runners.

## Validation

- Targeted pytest for remote Gaussian/job runner, ASE-NEB migration/pure tests,
  reference contract, import boundaries, and remote sync/job CLI.
- `python -m compileall -q src scripts tests`.
- `git diff --check`.
- Full pytest before commit.
- Sync authored checkout to `/home/iaw/.codex/skills/transition-state-workflow`
  and verify parity.

## Handoff

- Commit and push to `origin/main`.
- Mark the ASE/xTB remote adapter TODO completed only after tests, push, and
  installed-skill sync all pass.
