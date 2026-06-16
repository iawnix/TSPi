# TODO

## 2026-06-16 maintenance pass: remote metadata, preflight root, explorer copy, Gaussian Opt cap

Scope: fix these issues first in this GitHub-backed refactor checkout, then sync
the validated tree into the installed `transition-state-workflow` skill.

Status: implemented in this checkout on 2026-06-16. Keep this section until the
validated checkout has been synced into the installed skill tree.

### 1. Remote Gaussian runner metadata isolation

Problem: multiple concurrent Gaussian inputs under one
`nodes/<node_id>/outputs` directory share fixed job metadata filenames:
`run_gaussian_on_compute.sh`, `submit_receipt.txt`, `runner.nohup`,
`run_metadata.txt`, and `g16_driver.out`. Scientific outputs such as
`<input_stem>.out` and `%chk` are distinct, but job provenance can be overwritten.

Plan:
- Keep node-scoped execution, but make runner metadata input-stem scoped:
  `<stem>.run_gaussian_on_compute.sh`, `<stem>.submit_receipt.txt`,
  `<stem>.runner.nohup`, `<stem>.run_metadata.txt`, and
  `<stem>.g16_driver.out`.
- Keep compatibility for existing outputs: status/tail/fetch should still read
  legacy fixed names when stem-scoped files are absent.
- Keep remote execution logic under `src/transition_state_workflow/remote/`;
  script wrappers remain thin.

Validation:
- Add/update tests for dry-run runner text, background submit/verify, fetch,
  monitor status, and two-input same-node metadata names.
- Implemented: `tests/test_remote_gaussian.py`.

### 2. Initial mechanism-preflight node consistency

Problem: `ts_hypothesis_workspace.py init` writes workspace-level preflight
state but does not create a canonical tree root node. New workspaces can start
directly at a compute branch such as `n010_*`, while older workspaces have
`n000_mechanism_preflight`.

Plan:
- Add `init --with-preflight-node` to scaffold a real
  `n000_mechanism_preflight` node from the same mechanism data used for
  `mechanism_model.json`.
- Add a `preflight-node` helper for existing initialized workspaces.
- Keep explorer read-only; do not synthesize fake roots in the UI.
- Add validator warning when a workspace has compute branch roots but no
  explicit `mechanism_preflight` node.

Validation:
- Add CLI tests for `init --with-preflight-node` and `preflight-node`.
- Add validator tests for warning behavior.
- Confirm normalized explorer state shows `preflight_complete` only from real
  node state.
- Implemented: `tests/test_preflight_node.py`.

### 3. TS Explorer Copy buttons

Problem: Copy buttons in the right panel depend only on
`navigator.clipboard.writeText`, which is unreliable on `0.0.0.0:8766`, LAN
HTTP, and other non-secure browser contexts.

Plan:
- Remove JSON and file-viewer Copy buttons and the unused clipboard helper.
- Keep the explorer as read-only display logic; no new clipboard fallback.

Validation:
- Static grep confirms no `copyJson`, `copyFile`, or `copyToClipboard` remains.
- Existing explorer/static tests continue to pass.
- Implemented: static grep has no matches for clipboard/Copy entrypoints.

### 4. Gaussian Opt max-cycle keyword behavior

Problem: Gaussian can preserve `Opt=(...,MaxCycle(s)=N)` in the printed route
while still enforcing an ordinary Opt cap of 100 steps, then terminating with
`NStep=100`.

Plan:
- Do not add build-sensitive internal Gaussian options as a default.
- Extend Gaussian parsing with a diagnostic for requested `MaxCycle(s)` versus
  the printed optimization maximum and `NStep` termination.
- Document that endpoint continuations should default to explicit continuation
  nodes from final geometries when the cap remains 100.
- Treat any internal-option override as future opt-in only after a target-build
  probe.

Validation:
- Add parser tests for a mismatch between requested `MaxCycles=300` and
  printed `maximum of 100` / `NStep=100`.
- Update `references/gaussian_validation.md` to reflect the safer continuation
  strategy.
- Implemented: `tests/test_parse_log.py` covers the mismatch diagnostic.

### Validation run

- `python -m py_compile` on changed Python modules: passed.
- `pytest -q tests/test_remote_gaussian.py tests/test_preflight_node.py tests/test_parse_log.py tests/test_finalize_node.py::test_validator_warns_for_root_engine_artifacts_and_bad_checkpoint_paths tests/test_reference_contract.py tests/test_import_boundaries.py tests/test_no_undefined_names.py`: 71 passed, 1 skipped.
- `pytest -q`: 280 passed, 2 skipped.
- Installed skill sync validation under `/home/iaw/.codex/skills/transition-state-workflow`: targeted suite 71 passed, 1 skipped; full `pytest -q` 280 passed, 2 skipped.
