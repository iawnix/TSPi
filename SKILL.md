---
name: transition-state-workflow
description: Plan, run, validate, and reflect on transition-state searches using chemistry-hypothesis-driven workspace exploration, tree-structured mechanism branches, xTB/ASE candidate generation, Qbics dMECP candidate generation, Gaussian TS/frequency validation, IRC follow-up, and reaction-connectivity checks. Use for rigorous TS work, exploratory mechanism searches, failed or ambiguous TS searches, proton transfer/HAT/PCET/rearrangement mechanisms, remote compute jobs, or when merging QBICS dMECP and Gaussian validation workflows.
---

# Transition-State Workflow

Use this skill for rigorous transition-state work. Treat every route as one
branch in a chemistry hypothesis tree. Never collapse candidate generation,
frequency validation, IRC, endpoint optimization, and mechanism interpretation
into one claim.

The defining feature of this skill is chemistry-driven exploration: maintain a
workspace where chemical hypotheses, evidence, refutations, and validated facts
accumulate until a TS is found or the mechanism hypothesis is rejected.

## Non-Negotiables

- Start with a mechanism preflight from charge, multiplicity, atom mapping,
  reactant/product minima, and expected breaking/forming bonds.
- For exploratory, failed, or ambiguous searches, read
  `references/hypothesis_workspace.md` and maintain `mechanism_model.json`,
  `knowledge_base.md`, and `evidence_registry.json`.
- Maintain `tssearch_<system>/manifest.json`, `tree.json`, and
  `nodes/<node_id>/` from the first concrete action, even if only preparing
  inputs.
- For multi-step mechanisms, maintain `pathway_model.json` with
  `pathway-init`; tag step-scoped nodes with `--pathway-id` and `--step-id`.
  `accepted_ts` remains an elementary-step claim, not a whole-pathway claim.
- Record each branch with hypothesis, changed variables, raw outputs, parsed
  evidence, current node state fields, outcome code, mechanism reflection, and
  next decision.
- For accepted, ambiguous, open-shell, electronically delicate, or competing
  mechanism branches, record structured mechanism analysis: reaction type,
  reaction-center motion, electronic/spin/charge diagnostics, orbital or
  population descriptors when available, and energy/barrier implications.
  Read `references/mechanism_analysis_sources.md` before deciding which method
  can support each layer.
- Tool choice must follow the current chemical hypothesis; do not run NEB,
  QST, dimer, QBICS dMECP, Gaussian, or IRC as a default linear pipeline.
- Before choosing the next branch in an existing workspace, run
  `scripts/ts_hypothesis_workspace.py plan-next --root <tssearch_root>` and use
  its planning packet as context. `plan-next` summarizes gates, allowed action
  classes, planning focus, prioritized context items, and backtrack actions;
  the agent still decides the chemical hypothesis and tool.
- Initial reactant/product endpoints must be optimized before NEB, QST, IRC
  reference checks, or final connectivity claims.
- User-provided reactant/product structures are endpoint hypotheses until they
  are shown to be distinct minima or chemically defensible constrained
  references. For multicomponent or weakly bound systems, validate fragment
  identities and endpoint stability before using the structures as NEB endpoints.
- If endpoint optimization collapses the reactant/product pair, changes the
  intended reaction-center identity, or leaves only an arbitrary relative-pose
  difference, backtrack to endpoint discovery instead of starting or continuing
  NEB.
- Use QBICS dMECP only as candidate generation unless Gaussian TS/frequency and
  connectivity validation later pass.
- Report `accepted_ts` only after frequency validation and endpoint/IRC
  connectivity validation pass on the intended reaction.

## State Vocabulary

Use these scientific claim labels precisely. In `node.json`, you author only
three state decisions: `lifecycle_state`/`run_state` (where the job is in its
life), `claim_status` (the scientific claim), and — for failed, ambiguous, or
stopped branches — `outcome`/`outcome_code` (what specifically went wrong). For
successful claim statuses, `outcome` is derived automatically by `finalize-node`
and must not be picked by hand. `claim_level` is always derived from
`claim_status`; never write it as input. Do not write a single node-level
`status`.

- `not_evaluated`: no scientific claim has been evaluated.
- `endpoint_minima_ready`: reactant/product endpoint optimization and
  endpoint-identity checks are complete; this is a prerequisite state, not TS
  connectivity.
- `candidate_found`: a scan, NEB, dMECP, QST, dimer, or guessed geometry exists.
- `tsfreq_validated`: Gaussian normal termination, stationary point evidence,
  convergence evidence, and exactly one imaginary frequency.
- `irc_raw_completed`: IRC ran, but endpoints are not yet optimized or
  structurally checked.
- `endpoint_connected`: optimized or structurally checked endpoints match
  intended reactant/product by reaction-center metrics.
- `irc_connected`: forward/reverse IRC plus endpoint/reference checks connect
  the intended sides.
- `accepted_ts`: `tsfreq_validated` and connectivity validation both passed.
- `rejected`: chemically unsupported branch; must include reflection.
- `ambiguous`: evidence is mixed; must specify the missing diagnostic.

Use `lifecycle_state=prepared` for inputs/tree records that exist but have not
run. Numerical failures belong in `outcome=numerical_failure` with
`claim_status=not_evaluated` unless they also refute a chemical hypothesis. A
stopped job is
`run_state=stopped`, `claim_status=not_evaluated`, and
`outcome=administrative_stop`; it is not a chemical failure unless scientific
evidence was parsed before the stop.

State rendering (labels, colors, severity) is owned by one derived
`node_state` model in
`src/transition_state_workflow/config/state_contract.py` and emitted through
the normalizer. Raw `claim_status`, `outcome`, and `run_state` remain audit
fields, but they do not have separate user-facing label vocabularies. The
explorer UI renders `node_state` fields verbatim and keeps no vocabulary of its
own. To add or change a displayed state, change the state model and the tools —
never the UI.

## Core Workflow

1. Create or update the chemistry hypothesis workspace before running work.
   - If no tree exists, read `references/tree_schema.md`.
   - For exploratory tasks, read `references/hypothesis_workspace.md`.
   - Use `scripts/ts_hypothesis_workspace.py init` when starting a new workspace.
   - Create a mechanism hypothesis node and one child per chemically distinct
     method/route.

2. Run mechanism preflight before spending compute time.
   - Read `references/mechanism_reflection.md`.
   - Use total charge, multiplicity, atom identities, fragment composition, R/P
     connectivity changes, and likely electronic state to propose a mechanism
     class.
   - Decide which mechanism-analysis layers are required for this branch:
     reaction type, reaction-center geometry, electronic state, orbital or
     population descriptors, and energy profile.
   - Read `references/mechanism_analysis_sources.md` when choosing how those
     layers will be obtained for xTB, ASE/NEB, Gaussian, QBICS dMECP, IRC, or
     population-analysis follow-up.
   - Record provisional hypotheses, open questions, and required diagnostics in
     `mechanism_model.json` as the mechanism `analysis_plan`; do not treat them
     as validated facts or evidence-backed `mechanism_analysis`.

3. Discover and validate endpoints before path searches.
   - Treat supplied reactant/product files as reference endpoint hypotheses, not
     validated minima.
   - For separated, bimolecular, ion-pair, encounter-complex, or flexible
     multicomponent systems, separate fragment identity from whole-system pose.
     Relative orientation alone is weak evidence unless the mechanism requires a
     specific complex geometry.
   - Use the intended level or a documented lower-level preoptimization. If an
     unconstrained optimization collapses the endpoint pair, try chemically
     justified light constraints on key reaction-center distances and record the
     constraints explicitly.
   - Record endpoint charge/multiplicity, level, energy, key bonds, fragment
     identities, constraints, and whether each endpoint is a minimum or only a
     constrained reference.
   - Do not start NEB, QST, or Gaussian-NEB from endpoints that are not distinct
     on the chosen surface unless the branch is explicitly labeled as endpoint
     discovery or constrained candidate generation.

4. Build the next-action planning context.
   - Run `scripts/ts_hypothesis_workspace.py plan-next --root <tssearch_root>`
     before choosing a branch in an existing workspace.
   - Treat `blocking_gates`, `allowed_next_actions`,
     `forbidden_next_actions`, `planning_focus`, `context_items`,
     failed-branch reflections, and open questions as context for the agent
     decision.
   - If `planning_focus.mode=backtrack_decision_needed`, record the chemically
     meaningful backtrack target before opening a new child branch.
   - If `planning_focus.mode=backtrack_replan`, attach the next decision-card
     branch under `planning_focus.parent_for_new_branch`, which is the active
     backtrack event's `to_node`; do not continue below the failed node unless
     the hypothesis is explicitly changed and recorded.
   - Keep at most one `event_state=active` backtrack in a workspace. Use
     `update-backtrack` to resolve or supersede the current active backtrack
     before making another one active.
   - `plan-next` may draft decision-card suggestions, but it does not choose the
     chemistry. The agent must still decide the mechanism hypothesis, method
     level, observables, constraints, and compute cost.
   - In a multi-step pathway, `plan-next` scopes the gate sequence to the next
     incomplete pathway step. Do not reuse a previous step's TS/Freq or
     connectivity evidence as proof for the next step.

5. Choose the next tool from the chemical hypothesis.
   - For xTB/ASE/NEB, scans, dimer, QST, or broad orchestration, read
     `references/candidate_generation.md`.
   - For QBICS dMECP, read `references/qbics_dmecp.md`.
   - Before execution, create `nodes/<node_id>/decision_card.md` explaining why
     this tool is the right test and what would refute the branch.
   - A generated geometry is only `candidate_found`.

6. Validate candidates with Gaussian.
   - Read `references/gaussian_validation.md` when preparing or judging Gaussian
     TS/Freq jobs.
   - Use the bundled Gaussian scripts when available rather than rewriting
     parsers.

7. Run mode and connectivity checks.
   - Read `references/connectivity_validation.md` before making endpoint or IRC
     claims.
   - Use explicit bonds/angles around the reaction center. Do not rely on
     visualization alone.
   - Prefer lower-cost imaginary-mode displacement and endpoint optimization
     before IRC unless proof-level connectivity is required or ambiguity remains.

8. Reflect, update knowledge, and branch.
   - Every failed or ambiguous branch needs a mechanism reflection.
   - Use `--mechanism-analysis` on `finalize-node` when a branch changes the
     reaction-type, electronic, orbital, reaction-center, or energy
     interpretation from evidence. Mark unavailable layers explicitly instead
     of inferring missing diagnostics.
   - Use `scripts/ts_hypothesis_workspace.py finalize-node` to close completed
     nodes. Do not separately hand-edit `node.json`, `tree.json`,
     `evidence_registry.json`, `reflection.md`, `knowledge_base.md`,
     `mechanism_model.json`, or accepted-TS manifest state.
   - For multi-step pathways, pass `--pathway-id` and `--step-id` when
     finalizing the accepted TS for that elementary step so
     `pathway_model.json` can derive partial versus complete pathway state.
   - When evidence refutes or leaves ambiguous an entire pathway step, pass
     `--pathway-step-status rejected` or `--pathway-step-status ambiguous`
     with the step-scoped finalization. Ordinary failed branches should stay
     branch-local and should not update pathway step status.
   - Backtrack to the closest chemically meaningful ancestor, not simply the
     last failed job.

## Chemistry-Driven Tool Selection

- Use xTB/GFN methods for low-cost structure cleanup, endpoint preoptimization,
  conformer or pose screening, scan/NEB/dimer candidate generation, and broad
  branch exploration when many hypotheses must be tested. xTB results are
  search evidence, not final TS validation.
- Use Gaussian/DFT when the result will support a validated endpoint,
  stationary point, imaginary mode, barrier, or accepted mechanism claim. Also
  move to Gaussian when xTB changes the intended reaction-center identity,
  collapses endpoint references, gives suspect charge/spin behavior, or the
  mechanism is electronically delicate.
- Use scans for a dominant coordinate such as proton transfer, bond stretch, or
  angle-controlled rearrangement.
- Use NEB when optimized reactant/product minima are distinct and the atom
  mapping gives a chemically meaningful continuous path. Do not use NEB as the
  next expensive step when the supposed endpoints differ only by arbitrary
  fragment pose, collapse during optimization, or have not survived endpoint
  stability checks.
- Use xTB-NEB for path discovery and candidate generation after endpoint
  readiness is documented. Use Gaussian-force NEB only as a more expensive
  refinement branch when endpoints are reliable, the path hypothesis is strong,
  and lower-level evidence is not decisive. Neither xTB-NEB nor Gaussian-force
  NEB is an accepted TS without later TS/Freq and connectivity validation.
- Use QST2/QST3 when optimized endpoints and a chemically plausible TS guess
  are available at the Gaussian level.
- Use dimer when a local saddle is plausible but endpoint identity or path
  mapping is uncertain.
- Use QBICS dMECP when diabatic fragment definitions are chemically natural for
  atom transfer or bond switching.
- Use Gaussian TS/Freq to validate stationary point and imaginary mode only.
- Use displacement/connectivity checks or IRC to prove the TS connects the
  intended sides.

## Reporting Rules

For any state or claim update, include only the highest validated layer:

- candidate path and route if only a candidate exists;
- Gaussian `.out` path, level, energy, imaginary frequency if
  frequency-validated;
- forward/reverse IRC paths and endpoint assignment only after connectivity
  checks;
- `outcome`, `outcome_code`, and mechanism implication for rejected,
  ambiguous, or numerically failed branches.

Do not say "TS found" for:

- xTB-only, NEB-only, scan-only, QST guess-only, or dMECP-only outputs;
- a single imaginary frequency whose mode is endpoint-side, conformational, or
  wrong mechanism;
- raw IRC endpoints that were not optimized or checked against references.

## Bundled Resources

Python tooling follows a package layout:

- `src/transition_state_workflow/base/`: shared data models.
- `src/transition_state_workflow/chem/`: reusable Gaussian parsing and geometry
  helpers shared by workflow tools (single source for `PERIODIC_TABLE`,
  `COVALENT_RADII`, `Atom`, XYZ/orientation parsing, bond/angle spec parsing,
  vector math, bond length, angle/dihedral geometry, Gaussian orientation
  blocks, standard frequency-line parsing, and termination checks).
- `src/transition_state_workflow/config/`: canonical state model, vocabularies,
  and the v2 contract checks shared by the validator and normalizer.
- `src/transition_state_workflow/cli/`: public CLI contracts and re-exports for
  `CLIBase`, `CLIResult`, `Command`, and `CommandResult`.
- `src/transition_state_workflow/core/`: ChemKernel-facing planning and
  workspace state writers: workspace initialization, decision-card/node
  templates, evidence registry append, start-node, backtrack lifecycle, and
  `plan-next` planning packets.
- `src/transition_state_workflow/gate/`: ChemGate-facing read and closure
  logic: evidence gates, workspace validation, normalized explorer views, and
  `finalize-node`.
- `src/transition_state_workflow/tools/`: ChemTool protocol, capability
  vocabulary, and registry for execution tools.
- `src/transition_state_workflow/backends/`: Gaussian, xTB, ASE, and QBICS
  adapter boundaries for program-specific input/output metadata. The Gaussian
  backend owns TS/Freq log parsing and exposes parsed summary/status properties
  through `GaussianBackendAdapter.parse()`; it also owns external-Gaussian NEB
  SCF-energy and force-block parsers used by the ASE calculator adapter.
- `src/transition_state_workflow/remote/`: remote execution and synchronization
  boundary. `exec.py` owns the argv-only OpenSSH executor, `openssh.py` adapts
  it to `RemoteTransport`, `sftp.py` provides optional Paramiko SSH/SFTP,
  `mcp.py` provides an injected MCP transport boundary, `gaussian_runner.py`
  runs node-scoped remote Gaussian jobs, `gaussian_monitor.py` handles
  status/tail/fetch, and `sync.py`/`sync_cli.py` handle explicit metadata
  mirror synchronization.
- `src/transition_state_workflow/util/`: cross-cutting helpers —
  `cli.py` (the unified CLI core: `CLIBase`/`CLIResult` for argparse command
  entrypoints, `emit_json` for JSON stdout, `emit_stdout` for legacy text
  transcripts, `log`/`warn` plus raw relay helpers for stderr diagnostics, and
  `run_cli`/`CliError`, which render failures as a one-line
  `{"ok": false, "error": ...}` envelope), `json_io.py`, `path_utils.py`,
  `node_layout.py` (node directory resolution), and compatibility forwarding
  modules such as `remote_exec.py`.
- `src/transition_state_workflow/tool/`: concrete chemistry tool CLIs and
  compatibility entrypoints. `parse_gaussian_ts_result.py` writes parser
  artifacts through `CLIBase` while delegating Gaussian TS/Freq parsing to
  `backends/gaussian.py`; `gaussian_gen_preflight.py` also uses `CLIBase` for
  shared argument parsing, logging, JSON output, and error envelopes.
  The NEB toolkit lives in the `tool/ase_neb/` subpackage, split by concern into
  layered modules
  (`constants`/`errors`/`coerce` leaves; `geometry`/`gaussian_calc`;
  `config`/`mechanism`/`images`; `workspace`; `node_writers`/`driver`/
  `validation`/`external_gaussian`). `tool/ase_neb_framework.py` is the thin CLI
  on top. The dependency direction is strictly downward and covered by import
  boundary tests.
- `src/transition_state_workflow/web/static/`: static explorer UI assets
  loaded by the optional web service. State labels/colors come only from
  `config/state_contract.py`, shipped through the normalizer; the UI keeps no
  vocabulary of its own.
- `scripts/*.py`: thin CLI wrappers only; do not put workflow logic there.
  The convention is stdout = JSON result (`emit_json`), stderr = diagnostics
  and the failure envelope; most tools route their `main` through
  `util.cli.run_cli` for that.

- `references/hypothesis_workspace.md`: chemistry hypothesis workspace,
  evidence registry, decision cards, and knowledge-update rules.
- `references/tree_schema.md`: required tree layout and node fields.
- `references/mechanism_reflection.md`: mechanism preflight and
  failure-reflection checklist.
- `references/mechanism_analysis_sources.md`: method-specific evidence sources,
  reliability limits, and `--mechanism-analysis` templates.
- `references/candidate_generation.md`: xTB/ASE/NEB/QST/Dimer candidate rules.
- `references/qbics_dmecp.md`: QBICS dMECP setup, fragment checks, failure
  handling.
- `references/gaussian_validation.md`: Gaussian TS/Freq, remote execution,
  parsing, IRC setup.
- `references/connectivity_validation.md`: endpoint/IRC structural validation
  rules.
- `references/compute_hosts.md`: known remote toolchains and host-specific
  pitfalls.
- `references/explorer_service.md`: local read-only web visualization for a
  synced TS-search workspace, with source/state isolation rules.
- `scripts/ts_hypothesis_workspace.py`: initialize workspaces, create decision
  cards, append evidence, record or update backtrack events, emit `plan-next`
  agent planning packets, and finalize completed nodes through the packaged
  workflow tools.
- `scripts/ts_validate_workspace.py`: read-only validator for tree/node/evidence
  consistency, state invariants, and backtrack references.
- `scripts/ts_normalize_view.py`: read-only normalizer that emits
  `ts-explorer-graph-v2` without obsolete state aliases.
- `scripts/ts_node_exec.py`: run xTB, QBICS, ASE, or other local engine
  commands from `nodes/<node_id>/outputs` with node-scoped metadata and path
  environment variables.
- `scripts/ase_neb_framework.py`: prepare and run ASE-managed xTB/Gaussian NEB
  candidate-generation branches with the current node/tree layout.
- `scripts/prepare_gaussian_ts_input.py`: generate Gaussian TS/Freq inputs from
  XYZ.
- `scripts/gaussian_gen_preflight.py`: preflight and optionally repair Gaussian
  Gen/GenECP inputs before remote execution.
- `scripts/run_remote_gaussian.py`: run Gaussian through login and compute hosts.
- `scripts/ts_remote_status.py`, `scripts/ts_remote_tail.py`, and
  `scripts/ts_remote_fetch.py`: inspect or fetch node-scoped remote Gaussian
  outputs without starting new compute work.
- `scripts/ts_remote_gaussian.py`: combined status/tail/fetch remote Gaussian
  monitor.
- `scripts/parse_gaussian_ts_result.py`: parse Gaussian TS/Freq results.
- `scripts/ts_imaginary_mode_follow.py`: extract Gaussian imaginary-mode
  displacements and prepare node-scoped endpoint follow-up artifacts.
- `scripts/ts_descriptor_extract.py`: extract compact TS/frequency descriptors
  from validated Gaussian outputs and mode-displaced structures.
- `scripts/rmsd_connectivity_check.py`: structural endpoint connectivity
  validator.
- `scripts/ts_explorer_server.py`: local read-only web explorer for hypothesis
  trees, backtrack edges, decision cards, evidence, and reflections.
