# Transition-State Workflow Refactor TODO

This file tracks the standalone refactor branch under
`/home/iaw/Codex/Project/2026-06-13/transition-state-workflow-refactor`.
Do not edit the installed skill at
`/home/iaw/.codex/skills/transition-state-workflow` during this refactor.

## Ground Rules

- Preserve the scientific contract: endpoint readiness, candidate generation,
  TS/Freq validation, connectivity validation, and `accepted_ts` remain separate
  claim layers.
- Preserve existing CLI entrypoints under `scripts/` unless a change is
  explicitly documented and covered by compatibility tests.
- Keep `ChemKernel` as the only writer of scientific workspace state once it is
  introduced.
- Keep `ChemGate` as the single owner of evidence gates, finalization,
  validation, and accepted-TS derivation once it is introduced.
- Keep web service behavior read-only: it renders registered local mirrors and
  never starts jobs or edits TS-search workspaces.
- Commit and push each completed checkpoint so behavior can be traced or
  rolled back.

## Refactor Checklist

- [x] Create dated Project workspace:
      `/home/iaw/Codex/Project/2026-06-13/transition-state-workflow-refactor`.
- [x] Copy the current `transition-state-workflow` skill snapshot without
      modifying `/home/iaw/.codex/skills/transition-state-workflow`.
- [x] Initialize standalone Git repository and commit baseline snapshot.
      Commit: `f72c33d chore: import transition-state workflow skill snapshot`.
- [x] Create standalone Gitea repository and push baseline `main`.
      Remote: `http://gitea.qbitdeep.com/iaw/transition-state-workflow-refactor.git`.
- [x] Run baseline validation before refactor.
      Result: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m pytest -q -p no:cacheprovider`
      -> `177 passed, 2 skipped`.
- [x] Add import-boundary tests that lock the intended dependency direction:
      `base/config/util` leaves, `chem/backends` adapters, `core` planning,
      `gate` validation/finalization, `tools` execution, `remote` transport,
      and `web` read-only rendering.
- [x] Introduce `core/` with `ChemKernel` interfaces for node planning,
      workspace mutation, branch decisions, and pathway-aware state writes.
- [x] Introduce `gate/` with `ChemGate` interfaces for evidence classification,
      `finalize-node`, workspace validation, normalized state derivation, and
      accepted-TS gates.
- [x] Introduce `tools/` with a `ChemTool` protocol, tool-result envelope, and
      capability vocabulary:
      `candidate_generation`, `optimization`, `tsfreq_validation`,
      `connectivity_check`, and `descriptor_analysis`.
- [x] Add a concrete `ChemTool` registry grouped by capability.
- [x] Introduce `backends/` contracts for Gaussian, xTB, ASE, and QBICS
      input/output adapters so program-specific parsing can be moved out of
      control-flow code.
- [x] Add concrete Gaussian, xTB, ASE, and QBICS backend adapter modules.
      Gaussian now parses TS/Freq logs; xTB, ASE, and QBICS currently expose
      adapter boundaries plus filesystem artifact metadata.
- [x] Move Gaussian TS/Freq log parsing into `backends/gaussian.py`; keep
      `tool/parse_gaussian_ts_result.py` as the artifact-writing CLI and
      compatibility import path.
- [x] Move external-Gaussian NEB energy/force output parsers into
      `backends/gaussian.py`; keep `tool/ase_neb/gaussian_calc.py` as the
      calculator-construction layer with compatibility imports.
- [x] Move shared bond/angle spec parsing into `chem/geometry.py`; keep NEB and
      connectivity CLIs as thin error-adapter wrappers.
- [x] Introduce `remote/` contracts with `RemoteTransport`,
      `RemoteWorkspace`, and sync-plan abstractions.
- [x] Add concrete `OpenSSHTransport`.
- [x] Add future `SFTPTransport` and `MCPTransport` modules.
- [x] Add explicit metadata sync plan/run/verify service for remote mirrors.
- [x] Split local mirror synchronization from remote Gaussian execution:
      sync should be an explicit service step with plan, run, verify, and
      explorer-registry update phases.
- [x] Keep explorer service hot-registration behavior but move registry/server
      ownership to a web/API boundary that cannot import job execution modules.
- [x] Replace ad hoc logging imports with one package-level logging policy and
      one CLI diagnostics path.
- [x] Introduce `CLIBase`/`CLIResult` for shared argparse logging setup, JSON
      payload rendering, and standard `CliError` envelopes.
- [x] Migrate gate validator and normalizer CLIs onto `CLIBase` while keeping
      `validate_ts_workspace_contract` and `normalize_ts_workspace_to_explorer_graph`
      as business functions for non-CLI callers.
- [x] Move read-only gate logic (`evidence_gates`, `normalize_view`,
      `validate_workspace`) into `gate/`, with legacy `tool/` paths kept as
      compatibility re-exports.
- [x] Move node finalization logic into `gate/finalize.py`, with legacy
      `tool/finalize_node.py` kept as a compatibility re-export.
- [x] Move state-writing backtrack and start-node logic into `core/`, with
      legacy `tool/record_backtrack.py` and `tool/start_node.py` kept as
      compatibility re-exports.
- [x] Move next-action planning logic into `core/plan_next.py`; keep
      `tool/plan_next.py` as the ChemGate-injecting compatibility layer so
      existing CLI behavior still validates workspace and evidence gates.
- [x] Move evidence-registry append logic into `core/workspace_state.py`, with
      the existing `add-evidence` CLI dispatch preserved.
- [x] Move decision-card/node-template creation and plan-suggestion materialize
      logic into `core/workspace_state.py`, keeping the existing workspace CLI
      command names and arguments.
- [x] Move core `init` workspace file creation into `core/workspace_state.py`;
      keep explorer registration and explorer checklist generation in the CLI/
      web boundary.
- [x] Move remote Gaussian monitor/status/tail/fetch logic into
      `remote/gaussian_monitor.py`, with the legacy `tool/` import path kept as
      a compatibility wrapper.
- [x] Move remote Gaussian execution/layout/background/download logic into
      `remote/gaussian_runner.py`, with the legacy `tool/` import path kept as
      a compatibility wrapper.
- [x] Move the underlying OpenSSH executor into `remote/exec.py`, with
      `util/remote_exec.py` kept as a compatibility wrapper.
- [x] Update `SKILL.md` and `references/` after code boundaries exist; do not
      describe future architecture as current behavior before tests prove it.
- [ ] Run compatibility validation after each checkpoint:
      full pytest, script help smoke tests, strict workspace validator smoke,
      and normalized view smoke.
- [ ] Push every completed checkpoint to Gitea and record commit ids here.

## Completion Log

- 2026-06-13: Baseline copied, committed, pushed, and validated.
- 2026-06-13: Added initial architecture contracts for `base`, `core`, `gate`,
  `tools`, `backends`, `remote`, and `cli`; added import-boundary tests.
- 2026-06-13: Added `ChemToolRegistry`, backend adapter registry and Gaussian/
  xTB/ASE/QBICS adapter boundaries, `OpenSSHTransport`, and metadata sync
  planning tests. Existing CLI behavior is unchanged.
- 2026-06-13: Added `scripts/ts_remote_sync.py` with explicit `plan`, `run`,
  `verify`, and `register` stages for remote workspace mirror sync. Existing
  Gaussian remote runner remains unchanged.
- 2026-06-13: Moved explorer server ownership to `web/server.py` and static
  assets to `web/assets.py`; legacy `tool/` paths remain compatibility
  re-exports, and boundary tests block web imports of job execution modules.
- 2026-06-13: Moved actual evidence-gate, normalizer, validator, and pathway
  model logic into `gate/` and `base/`; old `tool/` import paths remain
  compatibility re-exports.
- 2026-06-13: Moved actual finalize-node implementation into
  `gate/finalize.py`; `tool/finalize_node.py` remains a compatibility import.
- 2026-06-13: Moved actual backtrack-event and start-node state writers into
  `core/backtrack.py` and `core/start_node.py`; old `tool/` modules remain
  compatibility imports.
- 2026-06-13: Moved actual plan-next planning implementation into
  `core/plan_next.py`; `tool/plan_next.py` now only injects ChemGate validator
  and TS/Freq evidence predicates for compatibility.
- 2026-06-13: Moved the `add-evidence` registry writer into
  `core/workspace_state.py`; the workspace CLI still exposes the same
  subcommand and argument contract.
- 2026-06-13: Moved `decision-card` node-template creation and
  `plan-next --write-decision-cards` materialization into
  `core/workspace_state.py`; `tool/hypothesis_workspace.py` now dispatches to
  core for those writes.
- 2026-06-13: Moved core `init` workspace file creation into
  `core/workspace_state.py`; `tool/hypothesis_workspace.py` now handles only
  CLI dispatch plus explorer registration/checklist for init.
- 2026-06-13: Moved remote Gaussian status/tail/fetch implementation into
  `remote/gaussian_monitor.py`; `tool/remote_gaussian_monitor.py` remains a
  compatibility import for existing scripts and tests.
- 2026-06-13: Moved remote Gaussian execution implementation into
  `remote/gaussian_runner.py`; `tool/run_remote_gaussian.py` remains a
  compatibility import for existing scripts and tests.
- 2026-06-13: Moved the underlying `OpenSSHRemoteExecutor` implementation into
  `remote/exec.py`; `util/remote_exec.py` remains a compatibility import.
- 2026-06-13: Added optional `ParamikoSFTPTransport` and injected-callable
  `MCPTransport` adapters under `remote/`, with tests for command and file
  transfer behavior.
- 2026-06-13: Updated remote Gaussian wrapper scripts to import the remote
  package directly while leaving old `tool/` imports available for
  compatibility.
- 2026-06-13: Updated `SKILL.md`, `references/compute_hosts.md`, and
  `references/gaussian_validation.md` to describe the current core/gate/remote
  layout and `remote/exec.py` executor ownership.
- 2026-06-13: Unified package CLI diagnostics in `util/cli.py` and moved
  remote/web stdout, warning, captured-stream, and service-log output onto that
  boundary. Added regression tests blocking remote/web direct `print()` or
  `sys.stdout`/`sys.stderr` writes.
- 2026-06-13: Logging checkpoint validation passed:
  `git diff --check`; targeted CLI/remote/web/import/reference tests
  `45 passed`; full pytest `197 passed, 2 skipped`; script help smoke
  `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-smoke.p984TM/tssearch_smoke`.
- 2026-06-13: Added `CLIBase` and `CLIResult` to the unified CLI core,
  re-exported them from `transition_state_workflow.cli`, and migrated the
  gate validator/normalizer entrypoints to the base class without changing
  their JSON output contract.
- 2026-06-13: CLIBase checkpoint validation passed:
  `git diff --check`; targeted CLI/gate/import/no-undefined tests
  `86 passed, 1 skipped`; full pytest `199 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-cli-smoke.kCw7Wo/tssearch_smoke`.
- 2026-06-13: Moved Gaussian TS/Freq log parsing into the Gaussian backend
  adapter. The old `tool/parse_gaussian_ts_result.py` module now delegates to
  backend parser functions while preserving `parse_log`, `parse_frequencies`,
  and `parse_convergence` compatibility imports.
- 2026-06-13: Gaussian backend parser checkpoint validation passed:
  `git diff --check`; targeted Gaussian parser/backend/import/no-undefined
  tests `34 passed, 1 skipped`; full pytest `201 passed, 2 skipped`; script
  help smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-backend-smoke.cFU7bo/tssearch_smoke`.
- 2026-06-13: Moved external-Gaussian NEB SCF-energy and force-block parsers
  from `tool/ase_neb/gaussian_calc.py` into `backends/gaussian.py`. The old
  imports remain available for the external Gaussian calculator path.
- 2026-06-13: External Gaussian force-parser checkpoint validation passed:
  `git diff --check`; targeted parser/ASE/backend/import/no-undefined tests
  `74 passed, 1 skipped`; full pytest `202 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-force-smoke.N8TbRc/tssearch_smoke`.
- 2026-06-13: Moved bond/angle spec parsing into `chem/geometry.py`; NEB keeps
  `ConfigError` wrapping and connectivity keeps `ValueError` wrapping while
  both use the same parser.
- 2026-06-13: Geometry parser checkpoint validation passed:
  `git diff --check`; targeted geometry/connectivity/ASE/import/no-undefined
  tests `60 passed, 1 skipped`; full pytest `202 passed, 2 skipped`; script
  help smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-geometry-smoke.pLTbEU/tssearch_smoke`.
