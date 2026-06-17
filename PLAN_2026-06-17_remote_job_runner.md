# 2026-06-17 Remote Job Runner Plan

## Scope

Close the remaining `/home/iaw/TS/.codex/TODO.md` feedback about the
Gaussian-biased remote runner without changing scientific TS-search results.

## Boundary

- Keep `remote/exec.py` as the argv-only SSH/login-host/compute-host boundary.
- Add `remote/job_runner.py` as the generic remote job lifecycle layer:
  directory preparation, file upload, runner chmod, foreground/background
  launch, receipt/nohup/metadata naming, fetch list, and download.
- Keep Gaussian-specific behavior in `remote/gaussian_runner.py`: node-scoped
  Gaussian layout, `.gjf` input handling, G16 environment, Gaussian output and
  checkpoint artifact groups, and the existing `run_remote_gaussian.py` CLI.
- Do not implement full xTB or ASE-NEB remote execution in this pass. The
  generic layer must make those engine adapters possible without reusing the
  Gaussian CLI.

## Implementation Steps

1. Introduce `RemoteJobSpec`, `RemoteJobRuntime`, and generic helper functions
   in `remote/job_runner.py`.
2. Refactor `remote/gaussian_runner.py` to build a Gaussian `RemoteJobSpec`
   and call the generic lifecycle helpers.
3. Move monitor/fetch shell snippets that are not Gaussian-specific into
   `remote/job_runner.py`, then leave `remote/gaussian_monitor.py` as the
   Gaussian artifact-pattern adapter.
4. Update references and SKILL resource listing to describe the current
   generic job runner plus engine-adapter boundary.
5. Add regression tests proving:
   - background submit/verify comes from the generic job runner;
   - Gaussian dry-run output remains node-scoped and compatible;
   - monitor status/tail/fetch reuse generic node-output commands;
   - no `os.system` or `shell=True` is introduced.

## Validation

- Targeted pytest: remote Gaussian, import boundaries, reference contract,
  architecture scaffold.
- Full pytest if targeted validation passes.
- `python -m compileall -q src scripts tests`.
- CLI smoke for `run_remote_gaussian.py --help`,
  `ts_remote_gaussian.py --help`, and thin status/tail/fetch wrappers.
- Sync authored checkout to `~/.codex/skills/transition-state-workflow`,
  then repeat targeted installed-tree checks.

## Handoff

- Commit and push to `origin/main`.
- Update `/home/iaw/TS/.codex/TODO.md` only after code, docs, tests, push, and
  installed-skill sync all pass.
