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
- [x] Move node-scoped local command execution into `tools/node_exec.py` with
      `NodeExecutionTool`; keep `tool/node_exec.py` as the CLI/compatibility
      entrypoint.
- [x] Introduce `backends/` contracts for Gaussian, xTB, ASE, and QBICS
      input/output adapters so program-specific parsing can be moved out of
      control-flow code.
- [x] Add concrete Gaussian, xTB, ASE, and QBICS backend adapter modules.
      Gaussian now parses TS/Freq logs; xTB, ASE, and QBICS currently expose
      adapter boundaries plus filesystem artifact metadata.
- [x] Move Gaussian TS/Freq log parsing into `backends/gaussian.py`; keep
      `tool/parse_gaussian_ts_result.py` as the artifact-writing CLI and
      compatibility import path.
- [x] Move Gaussian TS/Freq input rendering/preparation into
      `backends/gaussian.py`; keep `tool/prepare_gaussian_ts_input.py` as the
      CLI and compatibility import path.
- [x] Move external-Gaussian NEB energy/force output parsers into
      `backends/gaussian.py`; keep `tool/ase_neb/gaussian_calc.py` as the
      calculator-construction layer with compatibility imports.
- [x] Move shared bond/angle spec parsing into `chem/geometry.py`; keep NEB and
      connectivity CLIs as thin error-adapter wrappers.
- [x] Reuse `chem/gaussian_log.py` orientation-block parsing from Gaussian
      backend and connectivity tools instead of keeping duplicate parsers.
- [x] Reuse `chem/gaussian_log.py` standard frequency-line parsing from
      descriptor extraction so `freq=hpmodes` handling is centralized.
- [x] Move reusable vector, angle, and dihedral geometry calculations into
      `chem/geometry.py`; keep descriptor extraction as composition/output code.
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
- [x] Migrate the Gaussian TS/Freq parser artifact-writing CLI onto `CLIBase`
      while preserving `parse_log` and `build_parser` compatibility imports.
- [x] Migrate the Gaussian Gen/GenECP preflight CLI onto `CLIBase` while
      preserving `warnings_for`, `fix_lines`, and `build_parser` compatibility
      imports.
- [x] Migrate the Gaussian TS/Freq input-preparation CLI onto `CLIBase` while
      preserving pretty JSON output and old helper import names.
- [x] Migrate the node execution CLI onto `CLIBase` while preserving
      node-scoped cwd/env/metadata behavior and dry-run JSON output.
- [x] Move structural endpoint connectivity checking into
      `gate/connectivity.py`, with `tool/rmsd_connectivity_check.py` kept as a
      compatibility re-export and `scripts/rmsd_connectivity_check.py` pointing
      at the gate module directly.
- [x] Split descriptor extraction into the ChemTool layer:
      plan before code changes is to move Gaussian TS descriptor extraction
      from `tool/ts_descriptor_extract.py` to `tools/descriptors.py`, expose a
      `TSDescriptorExtractionTool` under `ToolCapability.DESCRIPTOR_ANALYSIS`,
      keep `tool/ts_descriptor_extract.py` as a compatibility re-export, point
      `scripts/ts_descriptor_extract.py` at the new tools module, and validate
      old helper imports plus CLI output artifacts before pushing.
- [x] Extract Gaussian descriptor parser helpers into the Gaussian backend:
      plan before code changes is to move Gaussian-specific descriptor text
      parsers from `tools/descriptors.py` to `backends/gaussian.py`, keep
      descriptor composition, ChemTool execution, and artifact output in
      `tools/descriptors.py`, preserve compatibility imports through
      `tool/ts_descriptor_extract.py`, and validate backend helper ownership,
      old helper imports, CLI output artifacts, script help, and full tests
      before pushing.
- [x] Move Gaussian Gen/GenECP preflight parsing and repair into the Gaussian
      backend:
      plan before code changes is to move `route_indices`, `split_tail`,
      `link0_end`, `warnings_for`, and `fix_lines` from
      `tool/gaussian_gen_preflight.py` to `backends/gaussian.py`; keep
      `tool/gaussian_gen_preflight.py` as the CLIBase argument/JSON wrapper
      and compatibility import path; point the public script at the same CLI;
      add import-boundary and parser behavior coverage; then validate
      preflight CLI behavior, script help, full tests, and workspace smoke
      before pushing.
- [x] Start ASE NEB migration by moving leaf support modules into the ChemTool
      layer:
      plan before code changes is to create `tools/ase_neb/`, move
      `constants`, `errors`, and `coerce` from `tool/ase_neb/` into that
      package, keep old `tool/ase_neb/{constants,errors,coerce}.py` as
      compatibility re-exports, update the remaining ASE NEB modules to import
      these leaf helpers from `tools/ase_neb`, and validate old/new import
      identity plus existing ASE NEB CLI and pure-function behavior before
      pushing.
- [x] Move ASE NEB geometry and mechanism pure logic into the ChemTool layer:
      plan before code changes is to move `tool/ase_neb/geometry.py` to
      `tools/ase_neb/geometry.py` first, keep the old geometry path as a thin
      compatibility re-export, and update remaining ASE NEB modules/tests to
      import geometry helpers from `tools/ase_neb`. Then move
      `tool/ase_neb/mechanism.py` to `tools/ase_neb/mechanism.py`, keep the
      old mechanism path as a thin compatibility re-export, update callers to
      the new path, and validate old/new import identity, pure helper behavior,
      public script help, full tests, and a strict workspace smoke before
      pushing.
- [x] Promote reusable geometry and mechanism primitives out of the ASE NEB
      tool package:
      plan before code changes is to split the current `tools/ase_neb/geometry.py`
      and `tools/ase_neb/mechanism.py` into generic chemistry primitives and
      ASE-NEB-specific adapters. Generic atom/XYZ parsing, covalent-radius
      connectivity, changed-bond detection, neighbor maps, angle inference, and
      fragment labels should live under `chem/geometry.py`. Generic
      reaction-center classification, coarse mechanism-hypothesis inference,
      electronic-state/risk-flag derivation, and endpoint-readiness vocabulary
      should live under a shared chemistry module such as `chem/mechanism.py`.
      Keep ASE object coercion, config-field extraction, `ConfigError`
      adaptation, and NEB policy wording in `tools/ase_neb/`; keep old
      `tool/ase_neb/geometry.py` and `tool/ase_neb/mechanism.py` as thin
      compatibility re-exports. Validate that non-NEB callers can import the
      shared primitives without importing ASE, tool-layer modules, or workspace
      writers.
- [x] Move ASE runtime loading before moving ASE image IO:
      plan before code changes is to move `require_ase`, `require_xtb`,
      `require_gaussian_calculator`, and `import_ase_bits` from
      `tool/ase_neb/gaussian_calc.py` into `backends/ase.py`, keep the old
      `gaussian_calc.py` helper names as compatibility imports, and only then
      move `tool/ase_neb/images.py` to `tools/ase_neb/images.py`. This avoids
      creating a reverse dependency from the new ChemTool layer back into the
      old `tool/` package. Validate old/new import identity, ASE-free config
      validation, public script help, full tests, and a strict workspace smoke
      before pushing.
- [x] Move ASE NEB config parsing into the ChemTool layer:
      plan before code changes is to move `ProjectContext`, config file
      reading, normalization, path resolution, level/node slug helpers, and
      `validate_config` from `tool/ase_neb/config.py` to
      `tools/ase_neb/config.py`. Keep `tool/ase_neb/config.py` as a thin
      compatibility re-export, update ASE NEB callers to import config helpers
      from `tools/ase_neb/config.py`, and keep dependency checks lazy through
      `backends/ase.py` so importing config remains ASE-free unless
      `require_deps=True`. Validate old/new import identity, compatibility
      wrapper length, no new architecture layer imports of `tool/`, public
      script help, full tests, and a strict workspace smoke before pushing.
- [x] Move ASE NEB workspace persistence into the ChemTool layer:
      plan before code changes is to move the NEB workspace I/O adapter from
      `tool/ase_neb/workspace.py` to `tools/ase_neb/workspace.py`: JSON/
      Markdown writing helpers, v2 node-record construction, tree/evidence
      registry updates, NEB project scaffold creation, node id generation, and
      shared report/reflection tail writing. Keep `tool/ase_neb/workspace.py`
      as a thin compatibility re-export and update ASE NEB callers to import
      workspace helpers from `tools/ase_neb/workspace.py`. This is still the
      ASE NEB tool adapter boundary; broader core extraction should happen
      later only when it can preserve the current dependency direction without
      making `tools/` import `core`. Validate old/new import identity,
      compatibility wrapper length, import boundaries, public script help, full
      tests, and a strict workspace smoke before pushing.
- [x] Move ASE NEB main-path node writers into the ChemTool layer:
      plan before code changes is to move `write_input_check_node` and
      `write_neb_node_metadata` from `tool/ase_neb/node_writers.py` to
      `tools/ase_neb/node_writers.py`. These functions translate a
      `ProjectContext`, normalized config, endpoint objects, and NEB summaries
      into node/evidence/report/reflection artifacts through the workspace
      adapter, so they belong with the ASE NEB ChemTool implementation rather
      than the legacy CLI package. Keep `tool/ase_neb/node_writers.py` as a
      thin compatibility re-export, update callers to import the new path, and
      validate old/new import identity, wrapper length, import boundaries,
      public script help, full tests, and a strict workspace smoke before
      pushing.
- [x] Constrain ASE NEB execution code to result production:
      plan before code changes is to add a structured ASE NEB result boundary
      under `tools/ase_neb/results.py`, use it for path-energy tables,
      force tables, candidate geometry metadata, and summary payloads, and make
      `tool/ase_neb/driver.py` stop importing any workspace writer. The
      driver may write tool-owned result artifacts under the supplied output
      directory, but it must return a result/summary object and leave
      `node.json`, `tree.json`, `evidence_registry.json`, reports, and
      reflections to core/CLI orchestration. Keep the public
      `write_path_summary` function compatible for now, add tests that ASE NEB
      driver imports do not touch workspace/node-writer modules, and validate
      public script help, full tests, and a strict workspace smoke before
      pushing.
- [x] Move ASE NEB workspace and node-state writing out of the ChemTool layer:
      plan before code changes is to promote the generic parts of
      `tools/ase_neb/workspace.py` into a core workspace writer boundary and
      replace `tools/ase_neb/node_writers.py` with a thin mapper from ASE NEB
      result payloads to core node/evidence write requests. The ASE NEB tool
      should expose result artifacts only; ChemKernel/core should own all
      workspace mutation. Keep compatibility imports until callers and tests
      prove the new core path is complete, then validate docs, import
      boundaries, public script help, full tests, and a strict workspace smoke.
- [x] Reclassify ASE NEB execution as an ASE backend adapter:
      plan before code changes is to stop treating ASE NEB as a ChemTool-owned
      implementation package. ASE is a backend that can drive xTB, Gaussian, or
      other calculators, while core owns chemistry hypotheses, workspace state,
      mechanism reflection, and tree maintenance. Move ASE NEB execution
      primitives, calculator construction, external-Gaussian force calculator,
      image-path result artifact writers, and NEB path-summary helpers into a
      backend module such as `backends/ase_neb.py` or an ASE backend package.
      Keep `tools/ase_neb/` as compatibility/adapter surface only for this
      checkpoint, and keep `tool/ase_neb/*` public imports working. Add import
      boundary tests that backend code does not import `core`, `tools`, or
      `tool`, and that ASE NEB state writes still route through core. Validate
      old/new import identity, public script help, full tests, and a strict
      workspace smoke before pushing.
- [x] Move external-Gaussian NEB continuation state writers into core:
      plan before code changes is to split `tool/ase_neb/external_gaussian.py`
      so it no longer owns workspace mutation. Move
      `external_gaussian_level_slug`, `continue_node_id_from_images`,
      `ensure_external_gaussian_project`, `write_external_image_input_node`,
      and `write_external_gaussian_neb_node` into a core module such as
      `core/ase_neb_external.py`, using only `base` and core workspace helpers.
      Keep the old `tool/ase_neb/external_gaussian.py` public imports working
      while reducing it to orchestration: read images, ask backend to produce
      path/result artifacts, ask core to write node/tree/evidence/report state,
      and return the CLI payload. Move candidate-quality summary/candidate JSON
      artifact updates into the ASE NEB backend result boundary. Add
      import-boundary tests that core external-Gaussian writers do not import
      `backends`, `tools`, or `tool`, and that old imports keep object identity.
      Validate external-Gaussian dry-run behavior, import boundaries, public
      script help, full tests, and a strict workspace smoke before pushing.
- [x] Split external-Gaussian NEB runtime request out of the tool layer:
      plan before code changes is to keep workspace-scoped fields such as
      `project_root`, `xyz_dir`, `pattern`, and `parent_node_id` in the tool
      orchestration request, but move backend runtime fields and behavior into
      `backends/ase_neb.py`. Add an `ExternalGaussianCalculatorRequest` (or
      equivalent) that owns route, charge, multiplicity, template/tail
      resolution, Gaussian command settings, normal-termination policy, output
      suffix, and calculator construction. Keep `ExternalGaussianRun` available
      from `tool/ase_neb/external_gaussian.py` for public callers, but make it
      delegate calculator construction and tail resolution to the backend
      request. Add tests for old/new import identity and tail-file/template
      behavior without requiring ASE, then validate import boundaries, public
      script help, full tests, and a strict workspace smoke before pushing.
- [x] Move external-Gaussian NEB continuation execution into the ASE backend:
      plan before code changes is to move force-route validation, dry-run
      first-input rendering, calculator attachment, NEB object construction,
      optimizer execution, path-summary writing, and candidate-quality artifact
      writing from `tool/ase_neb/external_gaussian.py` into
      `backends/ase_neb.py`. The tool layer should keep only workspace-scoped
      orchestration: create/read the source-image node, ask core to write
      node/tree/evidence state, call the backend runtime, and return the same
      CLI payload. Keep `ExternalGaussianRun`, `dry_run_gaussian_neb_inputs`,
      and `continue_gaussian_neb_from_images` available from the old import
      path, add backend/compatibility tests that do not require Gaussian, and
      validate import boundaries, public script help, full tests, and a strict
      workspace smoke before pushing.
- [x] Thin `ase_neb_framework.py` by moving command implementation into the
      ASE NEB workflow module:
      plan before code changes is to create `tool/ase_neb/workflow.py` for the
      command implementation and main-path orchestration that must compose core
      state writers, backend ASE runtime/result producers, config parsing, and
      validation-node helpers. Keep `ase_neb_framework.py` as the public parser
      and CLI dispatch module, preserve old public imports such as `prepare`,
      `run_neb`, `load_config_for_cli`, `make_gaussian_refine_from_cli`, and
      `evaluate_neb_candidate_quality`, and add import-boundary coverage that
      `ase_neb_framework.py` no longer imports backend/core runtime modules
      directly. Validate the ASE NEB CLI, compatibility imports, script help,
      full tests, and a strict workspace smoke before pushing.
- [x] Move main ASE NEB runtime execution out of the workflow module:
      plan before code changes is to add an `AseNebRuntimeRequest` and
      `run_ase_neb_candidate_path` backend API in `backends/ase_neb.py` for the
      standard endpoint-based ASE NEB run. That backend API should own reading
      prepared initial images, attaching calculators, constructing the NEB
      object, running the optimizer, writing final images/path summaries, and
      writing candidate-quality result artifacts. Keep `tool/ase_neb/workflow.py`
      as orchestration only: Gaussian opt-in policy, `prepare()`/pending node
      creation, final core node metadata, optional Gaussian refinement input,
      and CLI JSON. Add boundary tests that workflow no longer imports or names
      backend runtime internals directly, keep old public imports working, then
      validate targeted ASE/import tests, full tests, script help, and strict
      workspace smoke before pushing.
- [x] Move endpoint-based ASE NEB preparation into the backend:
      plan before code changes is to add a structured backend preparation
      result/API in `backends/ase_neb.py` that owns endpoint image loading,
      endpoint atom-order validation, NEB interpolation, and writing the
      backend-owned initial image/path artifacts. Keep
      `tool/ase_neb/workflow.py` as orchestration only: create the project
      scaffold, pass endpoint objects to core input-check state writers, write
      pending NEB metadata, and keep CLI behavior unchanged. Add boundary tests
      that workflow no longer imports or names the low-level image preparation
      helpers directly, keep old public imports working, then validate targeted
      ASE/import tests, full tests, script help, and strict workspace smoke
      before pushing.
- [x] Move NEB candidate validation policy into ChemGate:
      plan before code changes is to create `gate/neb_candidate.py` for
      backend-agnostic NEB candidate validation policy: displacement ladder
      selection, connectivity threshold policy, IRC requirement policy, and
      validation-policy payload construction from reactant/product endpoint
      structures. This is a scientific evidence gate, not an ASE backend
      validator. Keep `tool/ase_neb/validation.py` as the compatibility and
      CLI-adapter layer that preserves `ConfigError` behavior and keeps
      workspace/node writers in place until a later core split. Add
      import-boundary tests that the gate module imports no `tool`, `tools`,
      `core`, `backends`, `remote`, or `web` modules, and validate old/new
      policy behavior plus public script help, full tests, and strict workspace
      smoke before pushing.
- [x] Move Gaussian refinement input rendering out of the ASE NEB validation
      adapter:
      plan before code changes is to move `gaussian_refinement_defaults` and
      the ASE-NEB-promoted Gaussian TS/Freq `.gjf` rendering logic from
      `tool/ase_neb/validation.py` into `backends/gaussian.py`. The Gaussian
      backend should own program-input rendering from XYZ plus Gaussian config;
      `tool/ase_neb/validation.py` should keep old helper names only as
      compatibility/error-adapter wrappers. Preserve existing generated input
      text where practical, add backend/compatibility tests, and validate
      script help, full tests, and strict workspace smoke before pushing.
- [x] Move ASE NEB validation node/workspace writers into core:
      plan before code changes is to create `core/ase_neb_validation.py` for
      validation/refinement workspace state: promotable-candidate lookup,
      validation-parent inference, Gaussian TS/Freq node state writing, and
      validation-plan node/evidence/report/reflection/tree writing. Core must
      not import `backends`, `tool`, or `tools`; the tool adapter may compose
      the Gaussian backend input renderer with core state writers to preserve
      old public functions and `ConfigError` behavior. Add import-boundary and
      behavior tests, then validate public script help, full tests, and strict
      workspace smoke before pushing.
- [x] Split imaginary-mode follow-up across backend, gate, and core:
      plan before code changes is to move Gaussian-specific log/template
      reading, imaginary-mode extraction, IRC status parsing, final-geometry
      extraction, and endpoint-opt `.gjf` rendering out of
      `tool/imaginary_mode_follow.py` into `backends/gaussian.py`; move the
      endpoint/IRC connection-screen decision logic into `gate/connectivity.py`;
      and move node-scoped/legacy artifact layout writing for imaginary-mode
      endpoint follow-up into a core module such as `core/imaginary_mode_follow.py`.
      The public `tool/imaginary_mode_follow.py` and
      `scripts/ts_imaginary_mode_follow.py` should remain CLI adapters with the
      same commands, return codes, and JSON payloads. Add import-boundary tests
      that backend/gate/core do not import the legacy tool layer, add behavior
      tests for old/new helper ownership, then validate public script help,
      targeted imaginary-mode tests, full pytest, and a strict workspace smoke
      before pushing.
- [x] Move TS hypothesis workspace CLI assembly out of the legacy tool layer:
      plan before code changes is to create a dedicated
      `cli/hypothesis_workspace.py` module that owns argparse construction,
      subcommand dispatch, explorer-registration CLI policy, and the
      explorer-launch checklist text. `core/workspace_state.py` should keep
      only workspace/tree/evidence state mutation, `base/explorer_registry.py`
      should remain the registry writer, and `tool/hypothesis_workspace.py`
      should become a compatibility entrypoint/re-export preserving the
      existing public functions and `scripts/ts_hypothesis_workspace.py`
      behavior. Add import-boundary/compatibility tests, then validate public
      script help, targeted workspace/finalize tests, full pytest, and a strict
      workspace smoke before pushing.
- [x] Move ASE NEB framework CLI assembly out of the legacy tool layer:
      plan before code changes is to create a dedicated
      `cli/ase_neb_framework.py` module that owns argparse construction,
      command dispatch, and `ConfigError` to `CliError` translation for
      `scripts/ase_neb_framework.py`. The existing
      `tool/ase_neb/workflow.py` should keep tool-layer orchestration around
      backend runtime, core state writers, and gate policy helpers;
      `tool/ase_neb_framework.py` should become an executable compatibility
      entrypoint/re-export preserving old public helper imports such as
      `prepare`, `run_neb`, `load_config_for_cli`,
      `make_gaussian_refine_from_cli`, and `evaluate_neb_candidate_quality`.
      Add import-boundary/compatibility tests, then validate public script help,
      targeted ASE NEB/parsing tests, full pytest, and strict workspace smoke
      before pushing.
- [x] Promote the ASE NEB backend file into a backend subpackage:
      plan before code changes is to replace the current thick
      `backends/ase_neb.py` module with `backends/ase_neb/` while keeping
      `transition_state_workflow.backends.ase_neb` as the public facade.
      Split backend-internal responsibilities into cohesive modules:
      `contracts.py` for errors, constants, and request/result dataclasses;
      `images.py` for endpoint/image/XYZ loading, interpolation, and image-set
      IO; `gaussian_external.py` for external-Gaussian force calculators,
      template-tail handling, and dry-run input rendering; `results.py` for
      force tables, path summaries, and backend-owned candidate artifacts; and
      `runtime.py` for calculator construction, NEB object creation,
      optimizer execution, and standard/external NEB run APIs. Preserve all old
      public imports through `backends.ase_neb`, `tools/ase_neb/*`, and
      `tool/ase_neb/*`, and add import-boundary coverage that no module in the
      ASE NEB backend subpackage imports `core`, `gate`, `tool`, `tools`,
      `cli`, `remote`, or `web`. Validate old/new import identity, public
      script help, targeted ASE NEB/parsing tests, full pytest, and a strict
      workspace smoke before pushing.
- [x] Promote `core/plan_next.py` into a ChemKernel planning subpackage:
      plan before code changes is to replace the current thick
      `core/plan_next.py` module with `core/plan_next/` while keeping
      `transition_state_workflow.core.plan_next` as the public facade and
      preserving existing imports from `tool/plan_next.py` and
      `cli/hypothesis_workspace.py`. Split planning responsibilities into
      cohesive core-only modules: `contracts.py` for `PLAN_SCHEMA` and stable
      packet constants; `cli.py` for argparse registration only; `loader.py`
      for workspace/tree/node/evidence reads and conservative validation
      hooks; `pathway.py` for pathway-plan inference and pathway node filters;
      `phase.py` for planning-state, phase, and focus inference;
      `suggestions.py` for decision-card, finalization, reframe, and backtrack
      action suggestions; `context.py` for failed/reframe/evidence/context
      summaries and ranking; and `ids.py` for node id sorting and next-id
      helpers. Keep the subpackage within ChemKernel boundaries: no imports
      from `backends`, `gate`, `tool`, `tools`, `remote`, or `web`, and no
      workspace mutation beyond the existing plan-materialization flow owned
      by `core/workspace_state.py`. Validate compatibility imports, import
      boundaries, workspace/finalize/pathway/backtrack tests, full pytest,
      public script help, and a strict workspace smoke before pushing.
- [x] Promote `gate/validate.py` into a ChemGate validation subpackage:
      plan before code changes is to replace the current thick
      `gate/validate.py` module with `gate/validate/` while keeping
      `transition_state_workflow.gate.validate` as the public facade and
      preserving `scripts/ts_validate_workspace.py`, `tool/validate_workspace.py`,
      `cli/hypothesis_workspace.py`, and compatibility imports. Split
      validation responsibilities into cohesive ChemGate-only modules:
      `contracts.py` for validation constants and finding helpers; `cli.py`
      for `ValidateWorkspaceCLI` and `main`; `workspace.py` for the
      `validate_ts_workspace_contract` orchestration; `tree.py` for tree,
      index, parent-graph, pathway, and event checks; `nodes.py` for node v2
      contract and normalized-node checks; `evidence.py` for evidence registry
      and coverage checks; `finalization.py` for reflection/finalization
      artifact checks; `mechanism.py` for mechanism-model checks;
      `artifacts.py` for portable path, engine artifact, and Gaussian
      checkpoint policy; and `io.py` for JSON/file/node-dir walking helpers.
      Keep the subpackage within ChemGate boundaries: no imports from `core`,
      `backends`, `tool`, `tools`, `remote`, or `web`. Validate compatibility
      imports, import boundaries, validator/normalizer/finalize/workspace
      tests, full pytest, public script help, and a strict workspace smoke
      before pushing.
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
- [x] Run compatibility validation after each completed checkpoint through the
      node-exec ChemTool checkpoint: full pytest, script help smoke tests,
      strict workspace validator smoke, and normalized view smoke are recorded
      in the completion log below.
- [x] Push every completed checkpoint through the node-exec ChemTool checkpoint
      to Gitea and record commit ids here.

## Checkpoint Commits

- `f72c33d` `chore: import transition-state workflow skill snapshot`
- `206aaf5` `docs: track refactor plan in todo`
- `f2b62da` `refactor: scaffold architecture contracts`
- `189c579` `refactor: add tool backend remote registries`
- `0b837e9` `refactor: add explicit remote sync cli`
- `ec633d2` `refactor: move explorer server to web boundary`
- `e3d71de` `refactor: move gate logic out of tool layer`
- `322e4e1` `refactor: move finalize logic into gate layer`
- `4a02864` `refactor: move workspace state writers into core`
- `d1c8826` `refactor: move plan-next logic into core`
- `bd67f68` `refactor: move evidence registry writer into core`
- `4d7be78` `refactor: move decision card writer into core`
- `bf57b02` `refactor: move workspace init writer into core`
- `680dce6` `refactor: move remote gaussian monitor into remote layer`
- `ac4142f` `refactor: move remote gaussian runner into remote layer`
- `d6879f6` `refactor: move openssh executor into remote layer`
- `5c8796c` `feat: add sftp and mcp remote transports`
- `7a9e4eb` `refactor: point remote scripts at remote package`
- `ac7fdc4` `docs: update architecture layout references`
- `1c2a704` `refactor: centralize cli diagnostics`
- `ac6a00a` `refactor: add cli base for gate commands`
- `576204f` `refactor: move gaussian parser into backend`
- `57c737f` `refactor: move gaussian force parsers into backend`
- `85c3ccf` `refactor: share geometry spec parsers`
- `303c7b1` `refactor: reuse gaussian orientation parser`
- `c50f017` `refactor: share descriptor frequency parsing`
- `2221591` `refactor: share geometry descriptor math`
- `ac34ca0` `refactor: move gaussian parser cli to base`
- `2f2fd31` `refactor: move gaussian preflight cli to base`
- `84a0821` `refactor: move gaussian input prep to backend`
- `b63b845` `refactor: move node exec to chemtool layer`
- `f960c95` `docs: align node exec references with refactor`
- `90394a4` `refactor: move connectivity checker into gate`
- `d21df8e` `docs: record connectivity migration checkpoint`
- `83cc6c1` `refactor: move descriptor extraction into chemtool`
- `fc254ce` `docs: record descriptor migration checkpoint`
- `6800d39` `refactor: move descriptor parsers into gaussian backend`
- `ba9c6a2` `docs: record descriptor backend checkpoint`
- `d69d612` `refactor: move gaussian gen preflight into backend`
- `d04f981` `docs: record gaussian gen preflight checkpoint`
- `ba5cdd7` `refactor: move ase neb leaf helpers into tools`
- `bbfb11e` `docs: record ase neb leaf checkpoint`
- `5db4717` `refactor: move ase neb geometry mechanism into tools`
- `e37b59d` `docs: record ase neb geometry mechanism checkpoint`
- `9bf43b1` `docs: plan shared geometry mechanism extraction`
- `350aac6` `refactor: share chemistry geometry mechanism primitives`
- `1fbb43a` `docs: record shared chemistry primitive checkpoint`
- `c7e5a9e` `refactor: move ase runtime and image io boundaries`
- `18afbb5` `docs: record ase runtime image boundary checkpoint`
- `5077030` `docs: plan ase neb config migration`
- `8b73e20` `refactor: move ase neb config into tools`
- `37d3357` `docs: record ase neb config checkpoint`
- `ffe95b8` `docs: plan ase neb workspace migration`
- `202ee15` `refactor: move ase neb workspace into tools`
- `04200b9` `docs: record ase neb workspace checkpoint`
- `3060d69` `docs: plan ase neb node writer migration`
- `c3bbb71` `refactor: move ase neb node writers into tools`
- `458b47f` `docs: record ase neb node writer checkpoint`
- `a434900` `docs: plan ase neb result boundary correction`
- `979b4a1` `refactor: isolate ase neb result artifacts`
- `f9e7b52` `docs: record ase neb result boundary checkpoint`
- `77a9035` `refactor: move ase neb state writers into core`
- `e92d9da` `docs: record ase neb core state checkpoint`
- `5c5d500` `docs: plan ase neb backend reclassification`
- `2a14cbc` `refactor: move ase neb execution into backend`
- `c3da905` `docs: record ase neb backend checkpoint`
- `f445633` `refactor: move external gaussian neb state writers into core`
- `5c0c4a1` `docs: record external gaussian core checkpoint`
- `dd1bfd3` `refactor: move external gaussian runtime request into backend`
- `ed6b539` `refactor: move external gaussian continuation runtime into backend`
- `52a70e1` `refactor: move ase neb cli workflow out of framework`
- `dd19631` `refactor: move ase neb runtime into backend request`
- `110af47` `docs: record ase neb runtime backend checkpoint`
- `1962952` `docs: plan ase neb preparation backend migration`
- `0e2ba4e` `refactor: move ase neb preparation into backend`
- `89b3983` `docs: record ase neb preparation checkpoint`
- `dd0c639` `docs: plan neb candidate gate migration`
- `69980ba` `refactor: move neb candidate policy into gate`
- `aa6ba80` `docs: record neb candidate gate checkpoint`
- `b0617a8` `docs: plan ase neb validation writer split`
- `f97d138` `refactor: move gaussian refinement input rendering into backend`
- `b2244e1` `refactor: move ase neb validation state writers into core`
- `1c9df0c` `docs: record ase neb validation split checkpoint`
- `56ff2ef` `docs: plan imaginary mode follow split`
- `12fc211` `refactor: split imaginary mode follow boundaries`
- `583b0c2` `docs: record imaginary mode follow split checkpoint`
- `6d30953` `docs: plan workspace cli split`
- `cfbb981` `refactor: move workspace cli assembly into cli layer`
- `9147834` `docs: record workspace cli split checkpoint`
- `993eb59` `docs: plan ase neb cli split`
- `27620f7` `refactor: move ase neb cli adapters into cli layer`
- `92af38b` `docs: record ase neb cli split checkpoint`
- `c28f5de` `docs: plan ase neb backend package split`
- `c7c98f3` `refactor: split ase neb backend into package`
- `81ff3c5` `docs: record ase neb backend package split`
- `a6d8aa3` `docs: plan plan-next package split`
- `47c90be` `refactor: split plan-next into core package`
- `b8f5997` `docs: record plan-next package split`
- `8fa958c` `docs: plan validator package split`
- `ce1c074` `refactor: split workspace validator into gate package`

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
- 2026-06-13: Removed duplicate Gaussian orientation-block parsing from
  `backends/gaussian.py` and `tool/rmsd_connectivity_check.py`; both now reuse
  `chem/gaussian_log.py` while preserving their previous return contracts.
- 2026-06-13: Gaussian orientation parser checkpoint validation passed:
  `git diff --check`; targeted parser/connectivity/imaginary/import/no-undefined
  tests `22 passed, 1 skipped`; full pytest `202 passed, 2 skipped`; script
  help smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-orientation-smoke.lY7Elx/tssearch_smoke`.
- 2026-06-13: Descriptor frequency metadata and imaginary-vector parsing now
  reuse `chem/gaussian_log.standard_frequency_values`, avoiding a duplicate
  hpmodes guard and preventing `Frequencies ---` rows from being interpreted as
  standard imaginary-mode vectors.
- 2026-06-13: Descriptor frequency parser checkpoint validation passed:
  `git diff --check`; targeted descriptor/parser/import/no-undefined tests
  `18 passed, 2 skipped`; full pytest `203 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-descriptor-smoke.ulYEPL/tssearch_smoke`.
- 2026-06-13: Moved descriptor vector, angle, and dihedral math into
  `chem/geometry.py`; `tool/ts_descriptor_extract.py` now reuses those helpers
  for bond-length, angle, dihedral, and mode-projection descriptors.
- 2026-06-13: Geometry math checkpoint validation passed:
  `git diff --check`; targeted geometry/descriptor/import/no-undefined tests
  `66 passed, 2 skipped`; full pytest `204 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-geom-math-smoke.xenPe2/tssearch_smoke`.
- 2026-06-13: Migrated `tool/parse_gaussian_ts_result.py` to `CLIBase` for
  shared argparse logging/error behavior while keeping artifact writes and JSON
  output unchanged.
- 2026-06-13: Gaussian parser CLIBase checkpoint validation passed:
  `git diff --check`; targeted parser/CLI/import/no-undefined tests
  `34 passed, 1 skipped`; full pytest `205 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-parser-cli-smoke.O6AGUr/tssearch_smoke`.
- 2026-06-13: Migrated `tool/gaussian_gen_preflight.py` to `CLIBase` for shared
  argparse logging/error behavior while keeping Gen/GenECP warning detection,
  repair output, and compatibility imports unchanged.
- 2026-06-13: Gaussian preflight CLIBase checkpoint validation passed:
  `git diff --check`; targeted preflight/CLI/import/no-undefined tests
  `25 passed, 2 skipped`; full pytest `206 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-preflight-cli-smoke.xjAGD2/tssearch_smoke`.
- 2026-06-13: Moved Gaussian TS/Freq input rendering and XYZ frame selection
  into `backends/gaussian.py`. `GaussianBackendAdapter.prepare()` can now write
  `.gjf` inputs from an XYZ/output request; `tool/prepare_gaussian_ts_input.py`
  is a `CLIBase` wrapper that preserves the existing script arguments, pretty
  JSON payload, and legacy helper import names.
- 2026-06-13: Gaussian input backend checkpoint validation passed:
  `git diff --check`; targeted backend/prepare-CLI/import/no-undefined tests
  `52 passed, 2 skipped`; full pytest `209 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-gaussian-input-smoke.W0eUn9/tssearch_smoke`.
- 2026-06-13: Moved node-scoped local command execution into
  `tools/node_exec.py` and added `NodeExecutionTool` for ChemTool registry use.
  `tool/node_exec.py` now keeps the existing script arguments and compatibility
  helper names while delegating execution to the tools layer through `CLIBase`.
- 2026-06-13: Node execution ChemTool checkpoint validation passed:
  `git diff --check`; targeted node-exec/tools/import/no-undefined tests
  `34 passed, 1 skipped`; full pytest `212 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-node-exec-smoke.sj5zP0/tssearch_smoke`.
- 2026-06-14: Replaced installed-skill `ts_node_exec.py` examples in candidate
  generation and QBICS references with repo-local `scripts/ts_node_exec.py`,
  clarified that normal node execution relays wrapped engine stdout/stderr
  while dry-run emits JSON, and added a reference contract regression for
  repo-local script examples.
- 2026-06-14: Docs/code consistency repair validation passed:
  `git diff --check`; targeted reference/import/CLI/node-exec tests
  `31 passed`; full pytest `213 passed, 2 skipped`; script help smoke
  `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-doc-smoke.whuBAt/tssearch_smoke`.
- 2026-06-14: Moved structural endpoint connectivity checking from
  `tool/rmsd_connectivity_check.py` to `gate/connectivity.py`. The script now
  imports the gate module directly, while the old `tool/` path remains a thin
  compatibility re-export covered by import-boundary tests.
- 2026-06-14: Connectivity gate migration validation passed:
  `git diff --check`; targeted import/connectivity/reference tests
  `22 passed`; full pytest `214 passed, 2 skipped`; script help smoke
  `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-connectivity-smoke.JhDw02/tssearch_smoke`.
- 2026-06-14: Moved Gaussian TS descriptor extraction from
  `tool/ts_descriptor_extract.py` to `tools/descriptors.py`, added
  `TSDescriptorExtractionTool` for `ToolCapability.DESCRIPTOR_ANALYSIS`, pointed
  the script at the tools module, and kept the old `tool/` path as a thin
  compatibility re-export.
- 2026-06-14: Descriptor ChemTool migration validation passed:
  `git diff --check`; targeted architecture/import/parser/descriptor/reference
  tests `40 passed, 1 skipped`; full pytest `216 passed, 2 skipped`; script
  help smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-descriptor-tool-smoke.O1PKCy/tssearch_smoke`.
- 2026-06-14: Moved Gaussian-specific descriptor text parsers from
  `tools/descriptors.py` to `backends/gaussian.py`. `tools/descriptors.py`
  now keeps descriptor composition, `TSDescriptorExtractionTool`, and artifact
  output while old helper imports remain available through the compatibility
  path.
- 2026-06-14: Gaussian descriptor backend parser validation passed:
  `git diff --check`; targeted import/parser/architecture/descriptor/reference
  tests `57 passed, 1 skipped`; full pytest `216 passed, 2 skipped`; script
  help smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-backend-descriptor-smoke.AzxVay/tssearch_smoke` with validator
  summary `0 errors, 0 warnings`.
- 2026-06-14: Moved Gaussian Gen/GenECP preflight parsing and repair helpers
  from `tool/gaussian_gen_preflight.py` to `backends/gaussian.py`. The old
  `tool/` module now keeps CLIBase argument/JSON behavior and compatibility
  helper imports while backend owns Gaussian input-format logic.
- 2026-06-14: Gaussian Gen/GenECP backend preflight validation passed:
  `git diff --check`; `py_compile` for backend and CLI modules; targeted
  import/preflight/architecture/parser/reference tests `49 passed, 1 skipped`;
  full pytest `217 passed, 2 skipped`; script help smoke `18 scripts`; strict
  workspace validator and normalizer smoke on
  `/tmp/tswf-gen-preflight-smoke.BGkUdk/tssearch_smoke` with validator summary
  `0 errors, 0 warnings`.
- 2026-06-14: Started ASE NEB migration by moving leaf support modules
  `constants`, `errors`, and `coerce` into `tools/ase_neb/`. The old
  `tool/ase_neb/` leaf files now compatibility re-export the new ChemTool-layer
  definitions, and remaining ASE NEB modules import these helpers from
  `tools/ase_neb`.
- 2026-06-14: ASE NEB leaf-module migration validation passed:
  `git diff --check`; `py_compile` for `tools/ase_neb`, `tool/ase_neb`, and
  `tool/ase_neb_framework.py`; targeted ASE NEB/import/architecture tests
  `74 passed, 1 skipped`; reference/import retest `15 passed`; full pytest
  `218 passed, 2 skipped`; script help smoke `18 scripts`; strict workspace
  validator and normalizer smoke on
  `/tmp/tswf-ase-leaf-smoke.q5rqmC/tssearch_smoke` with validator summary
  `0 errors, 0 warnings`.
- 2026-06-14: Moved ASE NEB geometry/connectivity helpers and mechanism
  preflight/endpoint-readiness helpers into `tools/ase_neb/`. The old
  `tool/ase_neb/geometry.py` and `tool/ase_neb/mechanism.py` paths remain thin
  compatibility re-exports, while ASE NEB callers import the pure helpers from
  the ChemTool layer.
- 2026-06-14: ASE NEB geometry/mechanism ChemTool validation passed:
  `git diff --check`; `py_compile` for `tools/ase_neb`, `tool/ase_neb`, and
  `tool/ase_neb_framework.py`; targeted ASE NEB/import/architecture/reference
  tests `82 passed, 1 skipped`; full pytest `219 passed, 2 skipped`; script
  help smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-ase-geometry-mechanism-smoke.pGQaIE/tssearch_smoke` with validator
  summary `0 errors, 0 warnings`.
- 2026-06-14: Promoted reusable geometry/connectivity primitives from
  `tools/ase_neb/geometry.py` into `chem/geometry.py`, added shared
  mechanism-preflight helpers in `chem/mechanism.py`, and reduced
  `tools/ase_neb/geometry.py` / `tools/ase_neb/mechanism.py` to ASE NEB
  adapters over the shared chemistry layer.
- 2026-06-14: Shared chemistry primitive extraction validation passed:
  `git diff --check`; `py_compile` for `chem`, `tools/ase_neb`, `tool/ase_neb`,
  and `tool/ase_neb_framework.py`; targeted ASE NEB/import/architecture/reference
  tests `83 passed, 1 skipped`; full pytest `220 passed, 2 skipped`; script
  help smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-shared-chem-smoke.HVNjtR/tssearch_smoke` with validator summary
  `0 errors, 0 warnings`.
- 2026-06-14: Moved ASE runtime loading helpers
  `require_ase`, `require_xtb`, `require_gaussian_calculator`, and
  `import_ase_bits` into `backends/ase.py`; `tool/ase_neb/gaussian_calc.py`
  keeps compatibility helper names. Moved ASE NEB image IO from
  `tool/ase_neb/images.py` to `tools/ase_neb/images.py`; the old path is a
  thin compatibility re-export.
- 2026-06-14: ASE runtime/image IO boundary validation passed:
  `git diff --check`; `py_compile` for `backends/ase.py`, `tools/ase_neb`,
  `tool/ase_neb`, and `tool/ase_neb_framework.py`; targeted
  import/ASE NEB/architecture/reference/parser tests `102 passed, 1 skipped`;
  full pytest `222 passed, 2 skipped`; script help smoke `18 scripts`; strict
  workspace validator and normalizer smoke on
  `/tmp/tswf-ase-runtime-images-smoke2.XIypWO/tssearch_smoke` with validator
  summary `0 errors, 0 warnings`.
- 2026-06-14: Moved ASE NEB config parsing and normalization from
  `tool/ase_neb/config.py` to `tools/ase_neb/config.py`; the old path is a
  thin compatibility re-export, and ASE NEB callers import config helpers from
  the ChemTool layer.
- 2026-06-14: ASE NEB config ChemTool validation passed:
  `git diff --check`; `py_compile` for `tools/ase_neb/config.py`,
  `tool/ase_neb/config.py`, `tool/ase_neb_framework.py`, `tool/ase_neb`, and
  `tools/ase_neb`; targeted import/ASE NEB/architecture/reference tests
  `86 passed, 1 skipped`; targeted parser/no-undefined tests
  `17 passed, 1 skipped`; full pytest `223 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-ase-config-smoke.yvnB71/tssearch_smoke` with validator summary
  `0 errors, 0 warnings`.
- 2026-06-14: Moved ASE NEB workspace persistence from
  `tool/ase_neb/workspace.py` to `tools/ase_neb/workspace.py`; the old path is
  a thin compatibility re-export, and ASE NEB callers import workspace helpers
  from the ChemTool layer.
- 2026-06-14: ASE NEB workspace ChemTool validation passed:
  `git diff --check`; `py_compile` for `tools/ase_neb/workspace.py`,
  `tool/ase_neb/workspace.py`, `tool/ase_neb_framework.py`, `tool/ase_neb`,
  and `tools/ase_neb`; targeted import/ASE NEB/architecture/reference tests
  `87 passed, 1 skipped`; targeted parser/no-undefined tests
  `17 passed, 1 skipped`; full pytest `224 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-ase-workspace-smoke.8UUqcJ/tssearch_smoke` with validator summary
  `0 errors, 0 warnings`.
- 2026-06-14: Moved ASE NEB main-path node writers from
  `tool/ase_neb/node_writers.py` to `tools/ase_neb/node_writers.py`; the old
  path is a thin compatibility re-export, and the ASE NEB CLI imports node
  writers from the ChemTool layer.
- 2026-06-14: ASE NEB node-writer ChemTool validation passed:
  `git diff --check`; `py_compile` for `tools/ase_neb/node_writers.py`,
  `tool/ase_neb/node_writers.py`, `tool/ase_neb_framework.py`, `tool/ase_neb`,
  and `tools/ase_neb`; targeted import/ASE NEB/architecture/reference tests
  `88 passed, 1 skipped`; targeted parser/no-undefined tests
  `17 passed, 1 skipped`; full pytest `225 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-ase-node-writers-smoke.Vnf8nh/tssearch_smoke` with validator
  summary `0 errors, 0 warnings`.
- 2026-06-14: Isolated ASE NEB path/result artifact writing into
  `tools/ase_neb/results.py`. `tool/ase_neb/driver.py` now builds ASE NEB
  objects, attaches calculators, scores candidate quality, and compatibility
  exposes the result helper names without importing workspace or node-writer
  modules. The ASE NEB CLI and external-Gaussian continuation path now call the
  result writer from the ChemTool package directly.
- 2026-06-14: ASE NEB result-boundary validation passed:
  `git diff --check`; `py_compile` for `tools/ase_neb/results.py`,
  `tool/ase_neb/driver.py`, `tool/ase_neb_framework.py`,
  `tool/ase_neb/external_gaussian.py`, and `tests/test_import_boundaries.py`;
  targeted import/ASE NEB/reference tests `78 passed, 1 skipped`; targeted
  architecture/no-undefined/parser/gate tests `37 passed, 1 skipped`; full
  pytest `226 passed, 2 skipped`; script help smoke `18 scripts`; strict
  workspace validator and normalizer smoke on
  `/tmp/tswf-ase-result-smoke.Y48M22/tssearch_smoke` with validator summary
  `0 errors, 0 warnings`.
- 2026-06-14: Moved ASE NEB workspace and node-state writing into
  `core/ase_neb_workspace.py` and `core/ase_neb_nodes.py`, with shared
  project-context and naming helpers in `base/ase_neb.py`. The
  `tools/ase_neb/workspace.py`, `tools/ase_neb/node_writers.py`,
  `tool/ase_neb/workspace.py`, and `tool/ase_neb/node_writers.py` modules now
  forward to core; the ASE NEB CLI, external-Gaussian continuation, and
  validation-node writer call core state helpers directly.
- 2026-06-14: ASE NEB core-state writer validation passed:
  `git diff --check`; `py_compile` for `base/ase_neb.py`,
  `core/ase_neb_workspace.py`, `core/ase_neb_nodes.py`, compatibility
  forwarders, ASE NEB CLI, external-Gaussian continuation, and validation
  modules; targeted import/ASE NEB/reference tests `78 passed, 1 skipped`;
  earlier focused architecture/ASE tests `89 passed, 2 skipped`; full pytest
  `226 passed, 2 skipped`; script help smoke `18 scripts`; strict workspace
  validator and normalizer smoke on
  `/tmp/tswf-ase-core-smoke.UXuVPt/tssearch_smoke` with validator summary
  `0 errors, 0 warnings`.
- 2026-06-14: Reclassified ASE NEB runtime execution as backend code in
  `backends/ase_neb.py`: ASE image IO, NEB object construction, calculator
  attachment, external-Gaussian force calculation, path tables, force tables,
  trajectory snapshots, candidate geometry metadata, and summary payloads now
  live in the backend. `tools/ase_neb/images.py`, `tools/ase_neb/results.py`,
  `tool/ase_neb/driver.py`, and `tool/ase_neb/gaussian_calc.py` remain thin
  compatibility adapters; ASE NEB CLI orchestration and external-Gaussian
  continuation call backend result producers and core state writers separately.
- 2026-06-14: ASE NEB backend reclassification validation passed:
  `git diff --check`; `py_compile` for `backends/ase_neb.py`, ASE NEB CLI,
  external-Gaussian continuation, compatibility wrappers, constants, and
  errors; `tests/test_import_boundaries.py` `16 passed`; ASE NEB pure tests
  `48 passed`; ASE NEB compatibility tests `7 passed, 1 skipped`; Gaussian
  parser tests `17 passed`; reference/architecture/no-undefined tests
  `18 passed, 1 skipped`; full pytest `226 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-ase-backend-smoke.PovSte/tssearch_smoke` with validator summary
  `0 errors, 0 warnings`.
- 2026-06-14: Moved external-Gaussian NEB continuation state writing into
  `core/ase_neb_external.py`: level/node id helpers, external-Gaussian project
  scaffold, source-image input node writing, NEB node metadata, evidence,
  report, reflection, and tree updates now live in core. The old
  `tool/ase_neb/external_gaussian.py` import names remain available, but that
  module now orchestrates backend result production plus core workspace writes.
  Candidate-quality annotations for `candidate.json` and `summary.json` now
  live in the ASE NEB backend result boundary and are shared by main ASE NEB
  and external-Gaussian continuation paths.
- 2026-06-14: External-Gaussian NEB core-state split validation passed:
  `git diff --check`; `py_compile` for `backends/ase_neb.py`,
  `core/__init__.py`, `core/ase_neb_external.py`,
  `tool/ase_neb/external_gaussian.py`, `tool/ase_neb_framework.py`, and
  `tests/test_import_boundaries.py`; targeted import/ASE NEB/reference/
  no-undefined/architecture tests `90 passed, 2 skipped`; full pytest
  `227 passed, 2 skipped`; script help smoke `18 scripts`; strict workspace
  validator and normalizer smoke on
  `/tmp/tswf-ase-external-core-smoke.6sQdCb/tssearch_smoke` with validator
  summary `0 errors, 0 warnings`.
- 2026-06-14: Moved external-Gaussian runtime request behavior into
  `backends/ase_neb.py` as `ExternalGaussianCalculatorRequest`, which owns
  route/charge/multiplicity, template or tail-file resolution, Gaussian command
  settings, normal-termination policy, output suffix, and calculator
  construction. `tool/ase_neb/external_gaussian.py` still exposes
  `ExternalGaussianRun` for workspace-scoped orchestration, but it delegates
  tail resolution and calculator creation to the backend request.
- 2026-06-14: External-Gaussian runtime-request split validation passed:
  `git diff --check`; `py_compile` for `backends/ase_neb.py`,
  `tool/ase_neb/external_gaussian.py`, `tests/test_ase_neb_pure.py`, and
  `tests/test_import_boundaries.py`; targeted import/ASE NEB tests
  `74 passed, 1 skipped`; reference/no-undefined/architecture tests
  `18 passed, 1 skipped`; full pytest `229 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-ase-runtime-request-smoke.VAqNHi/tssearch_smoke` with validator
  summary `0 errors, 0 warnings`.
- 2026-06-14: Moved external-Gaussian NEB continuation execution into
  `backends/ase_neb.py`: force-route validation, dry-run first-input
  rendering, calculator attachment, NEB object construction, optimizer
  execution, path-summary writing, and candidate-quality artifact writing now
  live in the ASE backend. `tool/ase_neb/external_gaussian.py` remains the
  workspace-scoped orchestration wrapper that reads source images, delegates
  runtime work to the backend, asks core to write node/tree/evidence state, and
  preserves the existing CLI payload and public import path.
- 2026-06-14: External-Gaussian continuation backend validation passed:
  `git diff --check`; `py_compile` for `backends/ase_neb.py`,
  `tool/ase_neb/external_gaussian.py`, `tests/test_ase_neb_pure.py`, and
  `tests/test_import_boundaries.py`; targeted import/ASE NEB tests
  `75 passed, 1 skipped`; reference/no-undefined/architecture tests
  `18 passed, 1 skipped`; full pytest `230 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-ase-continuation-backend-smoke.LlFK1C/tssearch_smoke` with
  validator summary `0 errors, 0 warnings`.
- 2026-06-14: Moved ASE NEB command implementation and main-path orchestration
  out of `tool/ase_neb_framework.py` into `tool/ase_neb/workflow.py`.
  `ase_neb_framework.py` now keeps parser construction, dispatch, shared error
  translation, and compatibility re-exports for `prepare`, `run_neb`,
  `load_config_for_cli`, `make_gaussian_refine_from_cli`, and
  `evaluate_neb_candidate_quality`; it no longer imports backend or core
  runtime/state modules directly.
- 2026-06-14: ASE NEB framework thin-wrapper validation passed:
  `git diff --check`; `py_compile` for `tool/ase_neb_framework.py`,
  `tool/ase_neb/workflow.py`, `tests/test_import_boundaries.py`, and
  `tests/test_parsing_and_gates.py`; targeted import/ASE NEB/parsing tests
  `85 passed, 1 skipped`; reference/no-undefined/architecture tests
  `18 passed, 1 skipped`; full pytest `231 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-ase-framework-smoke.5wnxnJ/tssearch_smoke` with validator summary
  `0 errors, 0 warnings`.
- 2026-06-14: Moved the standard endpoint-based ASE NEB runtime execution out
  of `tool/ase_neb/workflow.py` and into `backends/ase_neb.py` as
  `AseNebRuntimeRequest` plus `run_ase_neb_candidate_path`. The backend now
  owns reading prepared initial images, calculator attachment, NEB object
  construction, optimizer execution, final image/result artifact writing, and
  candidate-quality artifact updates. `workflow.py` now keeps the policy and
  state orchestration around that backend request.
- 2026-06-14: ASE NEB main-runtime backend validation passed:
  `git diff --check`; `py_compile` for `backends/ase_neb.py`,
  `tool/ase_neb/workflow.py`, `tests/test_import_boundaries.py`, and
  `tests/test_ase_neb_pure.py`; targeted import/ASE NEB/parsing tests
  `86 passed, 1 skipped`; reference/no-undefined/architecture tests
  `18 passed, 1 skipped`; full pytest `232 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-ase-main-backend-smoke.lYLrqf/tssearch_smoke` with validator
  summary `0 errors, 0 warnings`.
- 2026-06-14: Moved endpoint-based ASE NEB preparation into
  `backends/ase_neb.py` as `AseNebPreparationResult` plus
  `prepare_ase_neb_initial_path`. The backend now owns endpoint image loading,
  atom-order validation, NEB interpolation, and initial image/path artifact
  writing. `tool/ase_neb/workflow.py` now keeps only project scaffold creation,
  core input-check state writing, pending NEB metadata, and CLI orchestration
  around that backend preparation result.
- 2026-06-14: ASE NEB preparation backend validation passed:
  `git diff --check`; `py_compile` for `backends/ase_neb.py`,
  `tool/ase_neb/workflow.py`, `tests/test_import_boundaries.py`, and
  `tests/test_ase_neb_pure.py`; targeted import/ASE NEB/parsing tests
  `87 passed, 1 skipped`; reference/no-undefined/architecture tests
  `18 passed, 1 skipped`; full pytest `233 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-ase-prepare-backend-smoke.bHku6f/tssearch_smoke` with validator
  summary `0 errors, 0 warnings`.
- 2026-06-14: Moved backend-agnostic NEB candidate validation policy into
  `gate/neb_candidate.py`: displacement ladders, connectivity threshold
  policy, IRC requirement policy, and validation-policy payload construction
  now live in ChemGate. `tool/ase_neb/validation.py` keeps the old import path,
  adapts gate `ValueError` failures back to `ConfigError`, and continues to
  own the remaining CLI/workspace orchestration until the later core split.
- 2026-06-14: NEB candidate gate validation passed:
  `git diff --check`; `py_compile` for `gate/neb_candidate.py`,
  `tool/ase_neb/validation.py`, `tests/test_import_boundaries.py`, and
  `tests/test_ase_neb_pure.py`; targeted import/ASE NEB/parsing tests
  `90 passed, 1 skipped`; reference/no-undefined/architecture tests
  `18 passed, 1 skipped`; reference-doc contract test `7 passed`; full pytest
  `236 passed, 2 skipped`; script help smoke `18 scripts`; strict workspace
  validator and normalizer smoke on
  `/tmp/tswf-neb-candidate-gate-smoke.bR0Q9B/tssearch_smoke` with validator
  summary `0 errors, 0 warnings`.
- 2026-06-14: Moved ASE-NEB-promoted Gaussian TS/Freq refinement input
  rendering into `backends/gaussian.py` via `gaussian_refinement_defaults`,
  `render_gaussian_refinement_input`, and `write_gaussian_refinement_input`.
  `tool/ase_neb/validation.py` now keeps `gaussian_refinement_defaults` and
  `write_gaussian_input` as compatibility/error-adapter wrappers, preserving
  existing `.gjf` text behavior where practical.
  Commit: `f97d138 refactor: move gaussian refinement input rendering into backend`.
- 2026-06-14: Gaussian refinement input backend validation passed:
  `git diff --check`; `py_compile` for `backends/gaussian.py`,
  `tool/ase_neb/validation.py`, `tests/test_import_boundaries.py`,
  `tests/test_ase_neb_pure.py`, and `tests/test_parse_log.py`; targeted
  import/ASE NEB/parsing tests `111 passed, 1 skipped`;
  reference/no-undefined/architecture tests `18 passed, 1 skipped`; full
  pytest `240 passed, 2 skipped`.
- 2026-06-14: Moved ASE NEB validation workspace state into
  `core/ase_neb_validation.py`: promotable-candidate lookup, candidate
  resolution, validation-parent inference, Gaussian TS/Freq node state writing,
  and validation-plan node/report/reflection/tree writing. The old
  `tool/ase_neb/validation.py` now composes the Gaussian backend input writer
  with core state writers and preserves `ConfigError` behavior for CLI callers.
  Commit: `b2244e1 refactor: move ase neb validation state writers into core`.
- 2026-06-14: ASE NEB validation state-writer validation passed:
  `git diff --check`; `py_compile` for `core/ase_neb_validation.py`,
  `core/__init__.py`, `tool/ase_neb/validation.py`,
  `tests/test_import_boundaries.py`, `tests/test_ase_neb_pure.py`, and
  `tests/test_parse_log.py`; targeted import/ASE NEB/parsing tests
  `115 passed, 1 skipped`; reference/no-undefined/architecture tests
  `18 passed, 1 skipped`; full pytest `244 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-ase-validation-split-smoke.AdQV9Y/tssearch_smoke` with validator
  summary `0 errors, 0 warnings`.
- 2026-06-14: Split imaginary-mode follow-up across backend/gate/core:
  Gaussian-specific TS/Freq mode extraction, QST-safe endpoint-template
  handling, final-geometry extraction, and endpoint-opt `.gjf` writing now live
  in `backends/gaussian.py`; endpoint and IRC connection-screen summaries now
  live in `gate/connectivity.py`; node-scoped/legacy layout resolution and
  artifact writing now live in `core/imaginary_mode_follow.py`.
  `tool/imaginary_mode_follow.py` remains the public CLI adapter preserving
  `prepare`, `compare`, `irc-compare`, and `make-opt` JSON/return-code
  behavior.
  Commit: `12fc211 refactor: split imaginary mode follow boundaries`.
- 2026-06-14: Imaginary-mode follow-up split validation passed:
  `git diff --check`; `py_compile` for `backends/gaussian.py`,
  `gate/connectivity.py`, `core/imaginary_mode_follow.py`, `core/__init__.py`,
  `tool/imaginary_mode_follow.py`, `tests/test_import_boundaries.py`, and
  `tests/test_imaginary_and_node_exec.py`; targeted imaginary/import/Gaussian
  tests `56 passed`; reference/no-undefined/architecture tests
  `18 passed, 1 skipped`; full pytest `247 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-imaginary-follow-split-smoke.WtVMpm/tssearch_smoke` with validator
  summary `0 errors, 0 warnings`.
- 2026-06-14: Moved TS hypothesis workspace CLI assembly into
  `cli/hypothesis_workspace.py`: argparse construction, subcommand dispatch,
  explorer-registration CLI policy, and explorer launch checklist text now
  live in the CLI layer. `scripts/ts_hypothesis_workspace.py` imports the new
  CLI owner directly, while `tool/hypothesis_workspace.py` remains an
  executable compatibility re-export. The TS/Freq reframe predicate used by
  `plan-next` now lives in `gate/evidence.py`, so the new CLI composes
  ChemKernel planning with ChemGate validation without importing the legacy
  tool layer.
  Commit: `cfbb981 refactor: move workspace cli assembly into cli layer`.
- 2026-06-14: Workspace CLI split validation passed:
  `git diff --check`; `py_compile` for `cli/hypothesis_workspace.py`,
  `tool/hypothesis_workspace.py`, `gate/evidence.py`, `tool/plan_next.py`, and
  `tests/test_import_boundaries.py`; import-boundary tests `23 passed`;
  workspace/finalize tests `67 passed`; pathway/backtrack tests `17 passed`;
  reference/no-undefined/architecture tests `18 passed, 1 skipped`; full
  pytest `248 passed, 2 skipped`; script help smoke `18 scripts`; strict
  workspace validator and normalizer smoke on
  `/tmp/tswf-workspace-cli-smoke.QZXyjK/tssearch_smoke` with validator summary
  `0 errors, 0 warnings`.
- 2026-06-14: Moved ASE NEB CLI adapters into `cli/`: parser/dispatch/error
  translation now lives in `cli/ase_neb_framework.py`; ASE NEB command
  adapters now live in `cli/ase_neb_workflow.py`,
  `cli/ase_neb_validation.py`, and `cli/ase_neb_external.py`. The extra
  workflow/validation/external move was required by the import-boundary rule
  that new architecture layers, including `cli`, must not import the legacy
  `tool` package. `scripts/ase_neb_framework.py` imports the new CLI owner
  directly, while `tool/ase_neb_framework.py`,
  `tool/ase_neb/workflow.py`, `tool/ase_neb/validation.py`, and
  `tool/ase_neb/external_gaussian.py` remain compatibility re-exports.
  Commit: `27620f7 refactor: move ase neb cli adapters into cli layer`.
- 2026-06-14: ASE NEB CLI adapter split validation passed:
  `git diff --check`; `py_compile` for `cli/ase_neb_framework.py`,
  `cli/ase_neb_workflow.py`, `cli/ase_neb_validation.py`,
  `cli/ase_neb_external.py`, the corresponding tool compatibility shims, and
  ASE/import/parsing tests; targeted import/ASE NEB/parsing tests `92 passed`;
  reference/no-undefined/architecture/import/ASE NEB/parsing tests
  `110 passed, 1 skipped`; full pytest `248 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-ase-cli-smoke.LVJB23/tssearch_smoke` with validator summary
  `0 errors, 0 warnings`.
- 2026-06-14: Promoted the ASE NEB backend from the single
  `backends/ase_neb.py` file into the `backends/ase_neb/` backend subpackage.
  The package keeps `transition_state_workflow.backends.ase_neb` as the public
  facade while splitting implementation into `contracts.py`, `images.py`,
  `gaussian_external.py`, `results.py`, and `runtime.py`. The legacy
  `tools/ase_neb/*` and `tool/ase_neb/*` compatibility imports continue to
  resolve through the facade.
  Commit: `c7c98f3 refactor: split ase neb backend into package`.
- 2026-06-14: ASE NEB backend package split validation passed:
  `git diff --check`; `py_compile` for the new `backends/ase_neb/` package and
  `tests/test_import_boundaries.py`; import-boundary tests `23 passed`;
  targeted ASE NEB/parsing tests `94 passed, 1 skipped`;
  reference/no-undefined/architecture/import/ASE NEB/parsing tests
  `135 passed, 2 skipped`; full pytest `248 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator and normalizer smoke on
  `/tmp/tswf-ase-backend-package-smoke.IDjUTq/tssearch_smoke` with validator
  summary `0 errors, 0 warnings`.
- 2026-06-14: Promoted `core/plan_next.py` into the `core/plan_next/`
  ChemKernel planning subpackage. The public
  `transition_state_workflow.core.plan_next` import surface is preserved by
  the package facade while implementation is split across `cli.py`,
  `contracts.py`, `loader.py`, `pathway.py`, `phase.py`, `suggestions.py`,
  `context.py`, and `ids.py`. `tool/plan_next.py` remains the ChemGate-
  injecting compatibility layer, and `cli/hypothesis_workspace.py` continues
  to import the core facade directly.
  Commit: `47c90be refactor: split plan-next into core package`.
- 2026-06-14: Plan-next package split validation passed:
  `git diff --check`; `py_compile` for `core/plan_next/`, `core/__init__.py`,
  `tool/plan_next.py`, `cli/hypothesis_workspace.py`, and
  `tests/test_import_boundaries.py`; import-boundary tests `23 passed`;
  workspace/finalize/pathway/backtrack tests `73 passed`;
  reference/no-undefined/architecture/import/workspace tests
  `114 passed, 1 skipped`; full pytest `248 passed, 2 skipped`; script help
  smoke `18 scripts`; strict workspace validator, normalizer, and plan-next
  smoke on `/tmp/tswf-plan-next-package-smoke.hbknQs/tssearch_smoke` with
  validator summary `0 errors, 0 warnings` and plan schema
  `ts-next-action-plan-v1`.
- 2026-06-14: Promoted `gate/validate.py` into the `gate/validate/` ChemGate
  validation subpackage. The public `transition_state_workflow.gate.validate`
  import surface is preserved by the package facade while implementation is
  split across `cli.py`, `contracts.py`, `workspace.py`, `tree.py`,
  `nodes.py`, `evidence.py`, `finalization.py`, `mechanism.py`,
  `artifacts.py`, and `io.py`. `scripts/ts_validate_workspace.py` and
  `tool/validate_workspace.py` continue to use the same public gate facade.
  Commit: `ce1c074 refactor: split workspace validator into gate package`.
- 2026-06-14: Workspace validator package split validation passed:
  `git diff --check`; script help smoke `18 scripts`; strict workspace
  validator and normalizer smoke on
  `/tmp/tswf-validator-package-smoke.EoQnzV/tssearch_smoke` with validator
  summary `0 errors, 0 warnings`; full pytest `249 passed, 2 skipped`.
