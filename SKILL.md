---
name: transition-state-workflow
description: Plan, run, validate, and reflect on transition-state searches with a chemistry-hypothesis-driven workspace, decision JSON mutations, explicit mechanism branches, molecular comparison, backend adapters, remote execution helpers, read-only web visualization, and final report assembly.
---

# Transition-State Workflow

Use this skill for exploratory transition-state work where the route is not a
fixed pipeline. Treat each node as a test of a chemistry hypothesis. Keep
candidate generation, TS/Freq validation, connectivity validation, accepted TS
audit, and pathway audit as separate evidence layers.

The workspace is the only trusted state source. Agents do not edit workspace
state files by hand. All mutations go through `ts_workspace` with a validated
decision JSON.

## Module Boundaries

- `ts_workspace`: the only writable control plane. It owns workspace bootstrap,
  node start and close, append-only updates, decision validation, workspace
  validation, report context, finalizers, and root state writes.
- `mol_comparator`: structural comparison only. It returns metrics, a verdict,
  and uncertainty that can become evidence; it never writes a workspace.
- `ts_runtime`: isolated Python runtime discovery only. It owns Conda
  environment manifests and interpreter selection; it never mutates TS
  workspace state files.
- `ts_backends`: local calculation adapters. Backends prepare commands and parse
  direct artifacts; they do not set node verdicts or accepted TS facts. Gaussian
  input construction and TS/Freq log parsing live in `ts_backends.gaussian`.
- `ts_render`: molecular visualization only. It returns node-scoped image,
  animation, and diagnostic artifacts; it never mutates workspace state files or
  makes chemistry verdicts.
- `ts_remote`: generic staging, submission, polling, fetch, and kill helpers.
  Remote code does not interpret chemistry. Gaussian remote execution lives in
  `ts_remote.gaussian`.
- `ts_web`: read-only explorer support. UI state must be separate from the
  source workspace. Web only renders — every label, color, and `claim_state`
  comes from the backend; the UI keeps no vocabulary of its own. Start it with
  `python scripts/ts_web.py serve --state-dir <state> --port 8766`. Pass
  `--source-root <root>` (repeat for multiple workspaces) and matching
  `--label <name>` to register on startup. Default bind is `0.0.0.0` for
  LAN-visible TS monitoring. Manage the registry with
  `python scripts/ts_web.py register|list|remove --state-dir <state> ...`.
- `ts_report`: final conclusion assembly from validated workspace evidence.

## Public Control Plane

The public workspace interface has seven commands:

```bash
python scripts/ts_workspace.py init_workspace --root <root>
python scripts/ts_workspace.py report_workspace --root <root>
python scripts/ts_workspace.py validate_decision --root <root> --decision-file decision.json
python scripts/ts_workspace.py start_node --root <root> --decision-file decision.json
python scripts/ts_workspace.py update_workspace --root <root> --decision-file decision.json
python scripts/ts_workspace.py end_node --root <root> --decision-file decision.json
python scripts/ts_workspace.py validate_workspace --root <root>
```

Except for first-time bootstrap, mutation commands must be traceable to a
decision JSON. The mutation command validates the decision internally; a
separate `validate_decision` call is only a preflight. Public preflight is
workspace-aware: it validates both the JSON shape and contextual requirements
such as required post-`n000` `payload.branch_context` provenance.

Gaussian local helper entrypoints are thin wrappers around backend boundaries:

```bash
python scripts/prepare_gaussian_ts_input.py --help
python scripts/parse_gaussian_ts_result.py --help
```

Runtime and visualization entrypoints:

```bash
python scripts/install_env.py --json
python scripts/ts_render.py diagnostic --json
python scripts/ts_render.py render input.xyz -o nodes/n001/outputs/render.png
python scripts/ts_render.py compare reactant.xyz ts.xyz product.xyz -o nodes/n001/outputs/compare.png
python scripts/ts_render.py animate irc.xyz -o nodes/n001/outputs/irc.mp4
```

After installation, public scripts and the Pi extension prefer the interpreter
recorded in `.runtime/env.json`. If no runtime manifest is present, scripts fall
back to the current Python so development checkouts remain testable.

Remote Gaussian execution is an internal `ts_remote.gaussian` adapter. Do not
expose or treat it as an independent public workflow command.

Run `report_workspace` before choosing or closing a node. The report gives the
agent the current hypothesis tree, evidence readiness, open questions, and
allowed decision shape.

Use `templates/decision/` as the runtime source for decision JSON shape. Files
under `tests/` are regression fixtures only and must not be used as operating
examples for real research mutations. Decision templates constrain provenance,
evidence roles, and closure semantics; they must not be read as a fixed retry
or branching policy.

## State Model

Persistent node state has only three public concepts:

- `phase`: the scientific claim layer under test.
- `lifecycle`: whether this node is still running, closed, or administratively
  stopped.
- `closure`: the close record, absent until a node is closed or stopped.

Valid phases:

- `preflight`
- `endpoint`
- `rp_conformer_generation`
- `candidate_generation`
- `tsfreq_validation`
- `connectivity_validation`
- `accepted_audit`
- `pathway_audit`

Valid lifecycle values:

- `running`
- `closed`
- `stopped`

On close, `closure.program_status` records execution facts:

- `completed`
- `failed`
- `stopped`
- `not_run`

`closure.claim_verdict` records the scientific judgment for the current phase:

- `supported`
- `refuted`
- `inconclusive`
- `not_evaluated`

For `pathway_audit`, `claim_verdict=supported` means the audit conclusion is
supported. It does not by itself mean the audited pathway or step is accepted.
Negative audits should expose an audit outcome such as pathway not accepted
through evidence/closure/reporting semantics, while the agent remains
responsible for deciding whether to open a new branch, stop, or ask the user.
When the user's request requires strict R->P proof or mandatory IRC, a negative
pathway audit closes only the current mechanism branch. It must not be treated
as completion of the overall research task unless the user explicitly stops the
search or no scientifically meaningful branch remains.

Specific program failures or chemical disagreements belong in `reason_code`,
`closure.program.facts`, `closure.mechanism.facts`, or evidence diagnostics.
They are not top-level node states.

## Workflow

1. Initialize a workspace with `init_workspace`.
2. For a fresh endpoint-based run, start an explicit `node_id=n000`
   `endpoint` or `preflight` node before candidate generation. Use it only for
   source hashes, charge/multiplicity, atom mapping, endpoint sanity checks,
   and the structured `initial_mechanism_hypothesis`. Close it before opening
   `n001`; do not put TS/Freq, IRC, connectivity, or accepted-TS claims in
   `n000`.
   Reactant/product endpoints define target basins for validation, not the
   candidate-generation method. Do not default to QST2/QST3 merely because R/P endpoints
   are available; justify QST use from endpoint optimization, atom mapping,
   conformer compatibility, and the elementary-step model.
3. Run `report_workspace` before deciding the next node.
4. Construct a decision JSON with the action, rationale, report reference,
   evidence references, and payload. Start from `templates/decision/` when a
   reusable shape is needed; do not copy JSON from `tests/`. Every post-`n000`
   mechanism node must include `payload.hypothesis_ref` that points to
  `mechanism_model.hypotheses[]`. Use optional `payload.solution_ref` only to
   group alternative search strategies under the same hypothesis; it is
   lineage metadata, not a new state, verdict, or retry policy. Every post-`n000`
   `start_node` must include `payload.branch_context` so the agent's intended
   graph relation is explicit.
   When a solution branch fails and the agent decides the chemical hypothesis
   remains viable, open the next branch with the same `payload.hypothesis_ref`,
   a new `payload.solution_ref`, and `payload.branch_context.relation`
   set to `new_solution_branch`. For `new_solution_branch`,
   `new_hypothesis_branch`, and `new_pathway_branch`, set `payload.parent_node`
   to `payload.branch_context.anchor_node`; `payload.branch_context.from_node`
   records the failed or triggering node. `ts_workspace` records and validates
   that topology; it must not decide whether to retry, switch solution, switch
   hypothesis, or stop.
5. Run `validate_decision` for preflight when useful.
6. Apply the mutation through `start_node`, `update_workspace`, or `end_node`.
7. Use `ts_backends`, `ts_remote`, and `mol_comparator` to create artifacts and
   evidence, then register evidence through `ts_workspace`. Keep node artifacts
   phase-owned: candidate-generation outputs stay under the candidate node;
   TS/Freq parse and mode-analysis outputs stay under the TS/Freq node; IRC and
   endpoint-assignment outputs stay under the connectivity node. If the active
   hypothesis declares stereochemical requirements, stereochemical endpoint
   matching is a separate `stereochemical_connectivity_gate` owned by the
   connectivity node. If a node consumes an upstream artifact, do not cite that
   upstream file as the primary evidence path. Write the current node's
   validation artifact under `nodes/<node>/outputs/...` and record upstream
   files in `nodes/<node>/outputs/artifact_manifest.json`.
8. Close the node with program facts, claim verdict, implication, and open
   questions.
9. Run `report_workspace` again before branching or stopping.
10. Use `ts_report` only after the workspace validates.

## References

Read only the reference needed for the current task:

- `references/workspace_contract.md`
- `references/decision_contract.md`
- `references/state_model.md`
- `references/pathway_model.md`
- `references/mol_comparator_contract.md`
- `references/runtime_environment.md`
- `references/render_contract.md`
- `references/report_template.md`
- `references/backend_contract.md`
- `references/remote_contract.md`
- `references/mechanism_reflection.md`
- `references/backend_selection.md`
- `references/candidate_generation.md`
- `references/gaussian_validation.md`
- `references/connectivity_validation.md`

Use `templates/artifact_manifest.json` when a node consumes files generated by
an earlier node. `update_workspace` rejects new path-bearing evidence whose
`path` points into another node's artifact directory.

## Reporting Rules

Report the highest validated layer only:

- candidate evidence when only candidates exist;
- TS/Freq evidence only after a parsed frequency result supports the phase;
- connectivity evidence only after endpoint assignment has been checked;
- accepted TS only after TS/Freq, strict connectivity, and any declared
  stereochemical gates are present;
- pathway conclusion only after a pathway audit.

Do not call a candidate, scan point, NEB image, dMECP structure, or isolated
imaginary frequency an accepted TS.
Do not report a negative `pathway_audit` as a successful pathway conclusion.
If `accepted_ts_refs` is empty and the audit outcome is not accepted, report the
failed branch and the next hypothesis branch separately.
