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
      Current modules expose the adapter boundary and filesystem artifact
      metadata; migration of program-specific parsers remains separate work.
- [x] Introduce `remote/` contracts with `RemoteTransport`,
      `RemoteWorkspace`, and sync-plan abstractions.
- [x] Add concrete `OpenSSHTransport`.
- [ ] Add future `SFTPTransport` and `MCPTransport` modules.
- [x] Add explicit metadata sync plan/run/verify service for remote mirrors.
- [ ] Split local mirror synchronization from remote Gaussian execution:
      sync should be an explicit service step with plan, run, verify, and
      explorer-registry update phases.
- [ ] Keep explorer service hot-registration behavior but move registry/server
      ownership to a web/API boundary that cannot import job execution modules.
- [ ] Replace ad hoc logging imports with one package-level logging policy and
      one CLI diagnostics path.
- [ ] Update `SKILL.md` and `references/` after code boundaries exist; do not
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
