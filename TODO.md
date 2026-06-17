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

## 2026-06-17 design TODO: Gaussian-External-xTB backend and backend-selection policy

Status: implemented and synced on 2026-06-18. Keep this section as the
implementation record for the Gaussian-External-xTB backend and backend
selection policy.

### 1. Python Gaussian-External-xTB backend

Problem: ADCR's useful idea is not its reaction-network workflow, but the
Gaussian External pattern that lets Gaussian drive TS/IRC/Freq steps while xTB
provides low-cost energy, gradient, and Hessian data. The current workflow has
xTB, ASE/xTB, ASE NEB, Gaussian-force NEB, QBICS dMECP, and Gaussian DFT
validation boundaries, but lacks a node-scoped Python backend for the specific
`Gaussian External -> xTB` use case.

Design boundary:
- Add a backend module under `src/transition_state_workflow/backends/`, for
  example `gaussian_external_xtb.py`.
- The backend must implement Gaussian External protocol parsing and response
  writing only. It must not own workspace state, tree mutation, final TS claims,
  or ADCR-style reaction-network expansion.
- Use direct xTB command execution for robust gradient/Hessian support first.
  ASE may be used as an optional structure/calculator helper only when it
  reduces risk and does not obscure Gaussian External units or Hessian handling.
- All execution must be node/job scoped. Preserve Gaussian External request
  files, generated xTB inputs, xTB logs, gradient/Hessian artifacts, and a
  structured JSON summary under the node output area.
- Expose a thin script wrapper, for example
  `scripts/gaussian_external_xtb.py`, suitable for Gaussian routes such as
  `External="python .../gaussian_external_xtb.py --workdir <node-output> ..."`.
- Document Gaussian-side route constraints in the backend reference: TS jobs
  generally need `NoMicro` with `External`, Opt and Freq should be split unless
  a target Gaussian/xTB combination is proven safe, Gaussian driver parallelism
  should not waste cores while xTB owns the expensive work, and heavy-element
  jobs may need a broad dummy basis such as `UGBS` so Gaussian's parser accepts
  the elements even though xTB supplies the energy model.

Scientific claim boundary:
- Gaussian-External-xTB can produce low-level TS guesses, IRC-like low-level
  connectivity hints, and candidate evidence only.
- It must never produce `accepted_ts`.
- Any promising result must still branch to Gaussian DFT TS/Freq validation and
  explicit mode/connectivity or IRC checks.

Implementation requirements:
- Parse Gaussian External input records for atom count, derivative level,
  charge, multiplicity, atomic numbers, coordinates, and embedded charges if
  present.
- Support energy-only, gradient, and Hessian requests. If Hessian is requested,
  prefer xTB native Hessian output; fail clearly if unavailable rather than
  silently returning zeros.
- Handle charge/multiplicity to xTB `--chrg` and `--uhf` mapping explicitly.
- Keep unit conversion tests for Hartree, Bohr/Angstrom, gradients, forces, and
  Hessian lower-triangle output.
- Make xTB method, accuracy, electronic temperature, parallelism, solvent, and
  executable path explicit CLI/config variables, not hidden defaults.

Validation:
- Unit tests for Gaussian External request parsing and response formatting.
- Unit tests for command construction without executing xTB.
- A dry-run fixture that writes deterministic mock xTB artifacts and verifies
  energy/gradient/Hessian conversion.
- CLI `--help` smoke and `python -m py_compile` for changed modules.
- Optional live smoke only on a host with verified Gaussian+xTB, using a tiny
  molecule and a short route; record the result as backend smoke, not TS proof.

### 2. Backend-selection policy for TS search

Problem: the workflow currently lists supported backends, but the agent still
needs sharper rules for choosing a backend from the chemical situation. Tool
selection must be mechanism-driven and should not become a fixed linear
pipeline.

Policy to document in `references/candidate_generation.md` or a dedicated
backend-selection reference:
- Use direct Gaussian DFT `Opt=(TS,CalcFC,NoEigen) Freq` when a chemically
  reasonable TS guess is available and the system size/cost is acceptable.
- Use Gaussian-External-xTB when the desired driver is Gaussian TS/IRC/Freq but
  the system needs cheap repeated gradients/Hessians for TS-guess generation,
  coordinate-driving refinement, or low-level IRC-like screening.
- Use ASE/xTB scan or constrained optimization when a dominant coordinate is
  known and endpoint identity is not yet strong enough for NEB.
- Use ASE/xTB NEB only when optimized or defensible endpoint references are
  distinct and atom mapping gives a meaningful continuous path.
- Use Gaussian-force NEB only after endpoint identity is reliable and lower-cost
  scan/NEB evidence justifies the cost; its maximum remains candidate evidence.
- Use dimer when a local saddle is plausible but endpoint mapping is weak.
- Use QST2 sparingly when both endpoint structures are chemically meaningful,
  atom order is reliable, and interpolation is expected to be reasonable; do
  not treat QST2 as a default replacement for a poor TS guess.
- Use QST3 even more sparingly: if a plausible TS guess is already available,
  prefer direct `Opt=TS`; only keep QST3 as a documented fallback when endpoint
  guidance plus a TS guess is chemically justified.
- Use QBICS dMECP only when diabatic fragment/state definitions are chemically
  natural for atom transfer or bond switching; final acceptance still requires
  Gaussian TS/Freq and connectivity validation.

Validation:
- Add reference-contract tests so docs do not claim that xTB, ASE, NEB, QST,
  dMECP, or Gaussian-External-xTB can directly produce `accepted_ts`.
- Add planner or rationale tests only if the implementation changes
  `plan-next`; otherwise keep this as decision-policy documentation first.

Implementation record:
- Added `src/transition_state_workflow/backends/gaussian_external_xtb.py` with
  EIn parsing, EOu serialization, Bohr-to-Angstrom XYZ rendering, direct xTB
  argv construction, gradient/Hessian artifact parsing, deterministic dry-run
  artifacts, explicit embedded-charge rejection, and candidate-only summary
  metadata.
- Added the thin wrapper `scripts/gaussian_external_xtb.py` and registered the
  backend as `gaussian-external-xtb`.
- Added `references/gaussian_external_xtb.md` and
  `references/backend_selection.md`; updated the main skill, candidate
  generation reference, and mechanism-analysis capability matrix.
- Added offline regression coverage in `tests/test_gaussian_external_xtb.py`
  plus registry and reference-contract updates.

Validation run:
- Authored checkout targeted tests:
  `tests/test_gaussian_external_xtb.py tests/test_backend_adapters.py
  tests/test_architecture_scaffold.py tests/test_import_boundaries.py
  tests/test_reference_contract.py tests/test_no_undefined_names.py`:
  71 passed, 1 skipped.
- Authored checkout full `pytest -q`: 321 passed, 2 skipped.
- Authored checkout `python -m compileall -q src scripts tests`: passed.
- Authored checkout `python scripts/gaussian_external_xtb.py --help`: passed.
- Installed skill tree diff against authored checkout, excluding git and cache
  directories: no differences.
- Installed skill targeted tests: 71 passed, 1 skipped.
- Installed skill full `pytest -q`: 321 passed, 2 skipped.
- Installed skill `python -m compileall -q src scripts tests`: passed.
- Installed skill `python scripts/gaussian_external_xtb.py --help`: passed.
