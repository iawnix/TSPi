---
name: transition-state-workflow
description: Plan, run, validate, and reflect on transition-state searches using chemistry-hypothesis-driven workspace exploration, tree-structured mechanism branches, xTB/ASE candidate generation, Qbics dMECP candidate generation, Gaussian TS/frequency validation, IRC follow-up, and reaction-connectivity checks. Use for rigorous TS work, exploratory mechanism searches, failed or ambiguous TS searches, proton transfer/HAT/PCET/rearrangement mechanisms, remote compute jobs, or when merging QBICS dMECP and Gaussian validation workflows.
---

# Transition-State Workflow

Use this skill for rigorous transition-state work. Treat every route as one
branch in a chemistry hypothesis tree. Never collapse candidate generation,
frequency validation, connectivity proof, endpoint optimization, and mechanism
interpretation into one claim.

The defining feature of this skill is chemistry-driven exploration: maintain a
workspace where chemical hypotheses, evidence, refutations, and validated facts
accumulate until a TS is found or the mechanism hypothesis is rejected.

## Public Control Plane

The public workspace interface is intentionally limited to six commands:

```bash
python scripts/ts_workspace.py init_workspace ...
python scripts/ts_workspace.py start_node ...
python scripts/ts_workspace.py end_node ...
python scripts/ts_workspace.py report_workspace ...
python scripts/ts_workspace.py validate_decision ...
python scripts/ts_workspace.py validate_workspace ...
```

Do not rely on older workspace subcommands or wrapper scripts; they are not
public compatibility surfaces.

- `init_workspace` creates the workspace root ledger and required files:
  `knowledge_base.md`, `manifest.json`, `mechanism_model.json`,
  `pathway_model.json`, `tree.json`, and `evidence_registry.json`, plus root
  directories `inputs/`, `nodes/`, `reports/`, `accepted/`, and `rejected/`.
- `start_node` creates one node and immediately marks it `Running`. It records
  the phase, operation, hypothesis, parent/input references, rationale,
  expected evidence, refutation criteria, and cost/risk. When a new node
  replaces a failed or ambiguous branch, `start_node --replaces-node ...`
  records the canonical replacement backtrack event with `new_branch_node`
  pointing to the newly created node.
- `end_node` closes one node as `Success`, `Error`, or `Stopped`. Closure must
  include a structured explanation with program facts, mechanism facts, an
  implication for planning, and any open questions.
- `report_workspace` emits the LLM-facing workspace context. It summarizes
  `current_phase` as an attention anchor, `claim_readiness` as evidence
  diagnostics, focus/context pointers, and the public response contract. It
  does not choose the route, method, or next command for the model.
- `validate_decision` checks a proposed LLM decision JSON against the
  `report_workspace` response contract before any workspace mutation.
- `validate_workspace` performs the read-only workspace contract check.

The model should only return one of these actions in a decision payload:
`start_node`, `end_node`, `ask_user`, or `stop`.

## State Model

The public node state has two required concepts:

- `phase`: where the node sits in the scientific workflow.
- `node_disposition`: the node execution disposition.

Valid phases:

- `preflight`
- `endpoint`
- `rp_conformer_generation`
- `candidate_generation`
- `tsfreq_validation`
- `connectivity_validation`
- `accepted_audit`
- `pathway_audit`

Valid `node_disposition` values:

- `Running`: the node has started and is not closed.
- `Stopped`: work stopped administratively or by user decision.
- `Error`: the program/runtime failed before producing a usable scientific
  conclusion.
- `Success`: the node closed with evidence for the phase-level claim.

Program/runtime failures and mechanism interpretation stay separated inside
`closure_explanation`; they are not additional top-level state vocabularies.
When a node closes, `closure_explanation.program` describes what the program
did or failed to do, while `closure_explanation.mechanism` describes what can
or cannot be inferred chemically.

Internal audit fields such as `claim_status`, `claim_level`, `outcome`,
`outcome_code`, `lifecycle_state`, and `run_state` are derived by validators,
normalizers, and explorer payload builders from `phase`, `node_disposition`,
evidence records, and closure explanations. They must not be persisted as
top-level `node.json` state and must not be requested from the model.

## Non-Negotiables

- Start with a mechanism preflight from charge, multiplicity, atom mapping,
  reactant/product minima, and expected breaking/forming bonds.
- Maintain `tssearch_<system>/manifest.json`, `tree.json`,
  `mechanism_model.json`, `knowledge_base.md`, `pathway_model.json`, and
  `evidence_registry.json` from the first concrete action.
- For multi-step mechanisms, keep pathway identity in `pathway_model.json` and
  tag step-scoped nodes with `--pathway-id` and `--step-id` on `start_node` and
  `end_node`.
- Initial reactant/product endpoints must be optimized before NEB, QST, IRC
  reference checks, or final connectivity claims.
- User-provided reactant/product structures are endpoint hypotheses until they
  are shown to be distinct minima or chemically defensible constrained
  references.
- If endpoint optimization collapses the reactant/product pair, changes the
  intended reaction-center identity, or leaves only an arbitrary relative-pose
  difference, close that node with `Error` or `Stopped` as appropriate and
  explain the facts in `closure_explanation`.
- Use QBICS dMECP only as candidate generation unless Gaussian TS/frequency and
  connectivity validation later pass.
- Report a TS as accepted only after frequency validation and endpoint/IRC
  connectivity validation pass on the intended reaction.
- Backtracking is a planning interpretation produced from
  `report_workspace`; do not open a new branch under a failed hypothesis unless
  the changed variable and mechanism implication are explicit in `start_node`.

## Core Workflow

1. Initialize a workspace.
   - Read `references/tree_schema.md` and
     `references/workspace_contract.md` for the stored artifact contract.
   - Run `init_workspace` before creating any node.
   - Record charge, multiplicity, reaction class, key atoms, and expected bond
     changes when known.

2. Run mechanism preflight before spending compute time.
   - Read `references/mechanism_reflection.md`.
   - Use atom identities, fragment composition, R/P connectivity changes, and
     likely electronic state to propose a mechanism class.
   - Record provisional hypotheses and required diagnostics in
     `mechanism_model.json`; do not treat them as validated facts.

3. Discover and validate endpoints before path searches.
   - Treat supplied structures as endpoint hypotheses.
   - Validate fragment identities and endpoint stability before using endpoints
     as NEB or QST references.
   - Close endpoint nodes with `end_node`; put program errors and mechanism
     implications in the closure explanation.

4. Build the decision context.
   - Run `report_workspace --root <tssearch_root>` before choosing the next
     node in an existing workspace.
   - Use `current_phase`, `current_phase_scope`, `claim_readiness`, `focus`,
     `situation.context_items`, failed-node closure explanations, and open
     questions as context for the next decision.
   - Treat `current_phase` as the current attention layer, not as a mandatory
     next command. Route and method selection remain model decisions recorded
     in the decision provenance.
   - Do not expect `blocking_gates`, `allowed_next_actions`, or
     `forbidden_next_actions` in `report_workspace`; missing evidence is
     represented under `claim_readiness`, and public commands are listed under
     `available_commands`.
   - Validate the proposed JSON with `validate_decision` before mutating the
     workspace.

5. Choose the next tool from the chemical hypothesis.
   - For method and level selection, read
     `references/backend_selection.md`.
   - For scans, NEB/string, dimer, QST, direct TS candidate optimization, or
     broad orchestration, read `references/candidate_generation.md`.
   - For Gaussian External xTB, read
     `references/gaussian_external_xtb.md`.
   - For low-level candidate to high-level TS/Freq refinement, read
     `references/refinement_ladder.md`.
   - For QBICS dMECP, read `references/qbics_dmecp.md`.
   - Create the branch with `start_node` before launching compute.
   - A generated geometry is only candidate evidence.

6. Validate candidates with Gaussian.
   - Read `references/gaussian_validation.md` when preparing or judging
     Gaussian TS/Freq jobs.
   - Use the bundled Gaussian scripts when available rather than rewriting
     parsers.

7. Run mode and connectivity checks.
   - Read `references/connectivity_validation.md` before making endpoint or IRC
     connectivity claims.
   - Use explicit bonds/angles around the reaction center.
   - Prefer lower-cost imaginary-mode displacement and endpoint optimization
     before IRC unless proof-level connectivity is required or ambiguity
     remains.

8. Reflect, update knowledge, and branch.
   - Every `Error`, `Stopped`, or chemically ambiguous result needs a closure
     explanation that separates program facts from mechanism implications.
   - Close completed work with `end_node`; do not hand-edit `node.json`,
     `tree.json`, `evidence_registry.json`, `reflection.md`,
     `knowledge_base.md`, `mechanism_model.json`, or accepted-state manifest
     fields.
   - Open the next branch only after reading `report_workspace`.

## Chemistry-Driven Tool Selection

- Choose the search strategy first: manual TS guess plus direct TS
  optimization, relaxed/constrained scan, NEB/string/GSM,
  dimer/eigenvector-following, QST fallback, reaction-network exploration, or
  MECP/dMECP.
- Choose the level/backend second. xTB/GFN, semiempirical methods,
  Gaussian-External-xTB, Gaussian-force execution, and Gaussian/DFT are
  surfaces or execution backends, not standalone search strategies.
- Use xTB/GFN or semiempirical levels for low-cost cleanup, endpoint
  preoptimization, conformer/pose screening, scan/NEB/dimer candidate
  generation, and broad branch exploration.
- Use Gaussian/DFT when the result will support a validated endpoint,
  stationary point, imaginary mode, barrier, or accepted mechanism claim.
- Use scans for a dominant coordinate such as proton transfer, bond stretch, or
  angle-controlled rearrangement.
- Use NEB when optimized reactant/product minima are distinct and atom mapping
  gives a chemically meaningful continuous path.
- Use QST2 only as a limited fallback when the elementary step, R/P structures,
  atom order, and mapping are reliable. Generally avoid QST3 unless a specific
  reason is recorded.
- Use dimer when a local saddle is plausible but endpoint identity or path
  mapping is uncertain.
- Use QBICS dMECP when diabatic fragment definitions are chemically natural for
  atom transfer or bond switching.
- Use Gaussian TS/Freq to validate stationary point and imaginary mode only.
- Use displacement/connectivity checks or IRC to prove the TS connects the
  intended sides.

## Reporting Rules

For any state or claim update, report only the highest validated layer:

- candidate path and route if only a candidate exists;
- Gaussian `.out` path, level, energy, and imaginary frequency if
  frequency-validated;
- forward/reverse IRC paths and endpoint assignment only after connectivity
  checks;
- `node_disposition`, `phase`, and closure explanation for stopped, errored,
  or closed nodes.

Do not say "TS found" for:

- xTB-only, NEB-only, scan-only, QST guess-only, or dMECP-only outputs;
- a single imaginary frequency whose mode is endpoint-side, conformational, or
  wrong mechanism;
- raw IRC endpoints that were not optimized or checked against references.

## Bundled Resources

- `scripts/ts_workspace.py`: public workspace control plane.
- `scripts/ts_normalize_view.py`: read-only normalizer for explorer payloads.
- `scripts/ts_node_exec.py`: run local engine commands from
  `nodes/<node_id>/outputs` with node-scoped metadata.
- `scripts/ase_neb_framework.py`: prepare and run ASE-managed xTB/Gaussian NEB
  candidate-generation branches.
- `scripts/ts_remote_job.py`: generic remote job CLI. Initial engine support is
  `--engine ase-neb`, which stages a remote tool runtime and runs ASE/xTB NEB
  through the generic remote lifecycle.
- `scripts/gaussian_external_xtb.py`: Gaussian External wrapper for xTB energy,
  gradient, and Hessian through EIn/EOu files.
- `scripts/prepare_gaussian_ts_input.py`: generate Gaussian TS/Freq inputs from
  XYZ.
- `scripts/run_remote_gaussian.py`: run Gaussian through the generic remote job
  lifecycle.
- `scripts/parse_gaussian_ts_result.py`: parse Gaussian TS/Freq results.
- `scripts/ts_imaginary_mode_follow.py`: prepare imaginary-mode endpoint
  follow-up artifacts.
- `scripts/rmsd_connectivity_check.py`: structural endpoint connectivity
  validator.
- `scripts/ts_explorer_server.py`: local read-only web explorer for hypothesis
  trees, evidence, node states, and reflections.

Reference files:

- `references/workspace_contract.md`: workspace artifacts, report contract,
  node lifecycle, and evidence rules.
- `references/tree_schema.md`: required tree layout and node fields.
- `references/mechanism_reflection.md`: mechanism preflight and
  failure-reflection checklist.
- `references/mechanism_analysis_sources.md`: method-specific evidence
  sources and reliability limits.
- `references/backend_selection.md`: mechanism-driven backend selection.
- `references/candidate_generation.md`: scan, NEB/string/GSM, dimer, QST,
  direct TS-candidate optimization, and reaction-network rules.
- `references/gaussian_external_xtb.md`: Gaussian External EIn/EOu protocol.
- `references/refinement_ladder.md`: low-level candidate to high-level
  refinement and validation chain.
- `references/qbics_dmecp.md`: QBICS dMECP setup and failure handling.
- `references/gaussian_validation.md`: Gaussian TS/Freq, remote execution,
  parsing, and IRC setup.
- `references/connectivity_validation.md`: endpoint/IRC structural validation.
- `references/compute_hosts.md`: known remote toolchains and host-specific
  pitfalls.
- `references/explorer_service.md`: local read-only web visualization.
