---
name: transition-state-workflow
description: Plan, run, validate, and reflect on transition-state searches with a chemistry-hypothesis-driven workspace, decision JSON mutations, backtracking mechanism branches, molecular comparison, backend adapters, remote execution helpers, read-only web visualization, and final report assembly.
---

# Transition-State Workflow

Use this skill for exploratory transition-state work where the route is not a
fixed pipeline. Treat each node as a test of a chemistry hypothesis. Keep
candidate generation, TS/Freq validation, connectivity validation, accepted TS
audit, and pathway audit as separate evidence layers.

The workspace is the only trusted state source. Agents do not edit workspace
ledgers by hand. All mutations go through `ts_workspace` with a validated
decision JSON.

## Module Boundaries

- `ts_workspace`: the only writable control plane. It owns workspace bootstrap,
  node start and close, append-only updates, decision validation, workspace
  validation, report context, finalizers, and root ledger writes.
- `mol_comparator`: structural comparison only. It returns metrics, a verdict,
  and uncertainty that can become evidence; it never writes a workspace.
- `ts_backends`: local calculation adapters. Backends prepare commands and parse
  direct artifacts; they do not set node verdicts or accepted TS facts.
- `ts_remote`: generic staging, submission, polling, fetch, and kill helpers.
  Remote code does not interpret chemistry.
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
separate `validate_decision` call is only a preflight.

Run `report_workspace` before choosing or closing a node. The report gives the
agent the current hypothesis tree, evidence readiness, open questions, and
allowed decision shape.

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

Specific program failures or chemical disagreements belong in `reason_code`,
`closure.program.facts`, `closure.mechanism.facts`, or evidence diagnostics.
They are not top-level node states.

## Workflow

1. Initialize a workspace with `init_workspace`.
2. Run `report_workspace` before deciding the next node.
3. Construct a decision JSON with the action, rationale, report reference,
   evidence references, and payload.
4. Run `validate_decision` for preflight when useful.
5. Apply the mutation through `start_node`, `update_workspace`, or `end_node`.
6. Use `ts_backends`, `ts_remote`, and `mol_comparator` to create artifacts and
   evidence, then register evidence through `ts_workspace`.
7. Close the node with program facts, claim verdict, implication, and open
   questions.
8. Run `report_workspace` again before branching, backtracking, or stopping.
9. Use `ts_report` only after the workspace validates.

## References

Read only the reference needed for the current task:

- `references/workspace_contract.md`
- `references/decision_contract.md`
- `references/state_model.md`
- `references/pathway_model.md`
- `references/mol_comparator_contract.md`
- `references/backend_contract.md`
- `references/remote_contract.md`
- `references/mechanism_reflection.md`
- `references/backend_selection.md`
- `references/candidate_generation.md`
- `references/gaussian_validation.md`
- `references/connectivity_validation.md`

## Reporting Rules

Report the highest validated layer only:

- candidate evidence when only candidates exist;
- TS/Freq evidence only after a parsed frequency result supports the phase;
- connectivity evidence only after endpoint assignment has been checked;
- accepted TS only after both TS/Freq and connectivity gates are present;
- pathway conclusion only after a pathway audit.

Do not call a candidate, scan point, NEB image, dMECP structure, or isolated
imaginary frequency an accepted TS.
