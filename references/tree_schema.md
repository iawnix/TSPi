# TS Workspace Tree Schema

This document describes the stored tree and node artifacts used by the
five-command workspace control plane.

Public commands:

- `init_workspace`: create the root ledger.
- `start_node`: create a node and mark it `Running`.
- `end_node`: close a node as `Success`, `Error`, or `Stopped`.
- `report_workspace`: emit constrained decision context.
- `validate_decision`: check a proposed decision JSON before mutation.

## Root Layout

Required root files:

- `manifest.json`
- `tree.json`
- `evidence_registry.json`
- `mechanism_model.json`
- `pathway_model.json`
- `knowledge_base.md`

Required directories are created as needed:

- `nodes/`
- `reports/`
- `accepted/`
- `rejected/`
- `inputs/`

## `tree.json`

`tree.json` is the compact graph index:

```json
{
  "schema": "ts-tree-v1",
  "nodes": {
    "n010_endpoint": {
      "parent": null,
      "children": ["n020_candidate"],
      "stage": "endpoint",
      "status": "Success",
      "node_path": "nodes/n010_endpoint/node.json"
    }
  },
  "active_frontier": ["n020_candidate"],
  "closed_nodes": ["n010_endpoint"],
  "accepted_nodes": [],
  "events": [],
  "backtrack_events": []
}
```

The public display fields are `phase` and `node_disposition`. The tree may keep
additional internal indexes so validators and the explorer can check
consistency.

## `node.json`

Every node has a `nodes/<node_id>/node.json` file. The public fields are:

```json
{
  "node_id": "n020_candidate",
  "parent_id": "n010_endpoint",
  "phase": "candidate_generation",
  "node_disposition": "Running",
  "operation": "xtb-neb-screen",
  "hypothesis": "Endpoint-ready references can produce a TS candidate.",
  "decision_provenance": {
    "trigger_source": "agent_cli_decision_card",
    "parent_selection_reason": "Endpoint node closed successfully.",
    "changed_variables": {
      "operation": "xtb-neb-screen"
    }
  }
}
```

Closed nodes must include `closure_explanation`:

```json
{
  "phase": "candidate_generation",
  "node_disposition": "Error",
  "closure_explanation": {
    "schema": "ts-node-closure-v1",
    "program": {
      "summary": "The candidate job failed before producing a parsed candidate.",
      "facts": [
        {
          "text": "The program exited nonzero.",
          "source_path": "nodes/n020_candidate/outputs/run_metadata.txt"
        }
      ]
    },
    "mechanism": {
      "summary": "The program failure does not refute the proposed mechanism.",
      "facts": [
        {
          "text": "No reaction-center diagnostic was produced."
        }
      ]
    },
    "implication": "Open a revised candidate-generation node.",
    "open_questions": []
  }
}
```

Valid phases:

- `preflight`
- `endpoint`
- `rp_conformer_generation`
- `candidate_generation`
- `tsfreq_validation`
- `connectivity_validation`
- `accepted_audit`

Valid dispositions:

- `Running`
- `Stopped`
- `Error`
- `Success`

## Internal Audit Fields

The stored node may include internal audit fields such as:

- `claim_status`
- `claim_level`
- `outcome`
- `outcome_code`
- `lifecycle_state`
- `run_state`

These fields are written by tools and consumed by validators, normalizers, and
the explorer. They are not LLM-facing response fields. `report_workspace`
filters the decision context and publishes an `allowed_response_contract` so
the model knows what it may return.

Do not hand-author internal audit fields in a model decision. Use
`validate_decision` to reject any proposed response that contains them.

## Node Creation

Use `start_node` before launching compute:

```bash
python scripts/ts_workspace.py start_node \
  --root tssearch_example \
  --node-id n020_candidate \
  --parent-id n010_endpoint \
  --phase candidate_generation \
  --operation xtb-neb-screen \
  --hypothesis "Endpoint-ready references can produce a candidate." \
  --rationale "Candidate generation is the next gated phase." \
  --expected-evidence "candidate geometry and parsed summary" \
  --refutation-criteria "no candidate, wrong reaction center, or program error"
```

`start_node` writes `node.json`, a readable `decision_card.md`, node-scoped
directories, and tree index entries. It marks the node as `Running`.

Use `--input-ref` when a new node depends on files or evidence from another
node. Use `--pathway-id` and `--step-id` for pathway-scoped nodes.

## Node Closure

Use `end_node` for post-execution closure:

```bash
python scripts/ts_workspace.py end_node \
  --root tssearch_example \
  --node-id n020_candidate \
  --node-disposition Success \
  --phase candidate_generation \
  --decision prepare_tsfreq_validation \
  --summary "A candidate geometry was generated." \
  --primary-file nodes/n020_candidate/parsed/candidate.json \
  --evidence '{"kind":"candidate_summary","path":"nodes/n020_candidate/parsed/candidate.json","claim":"A candidate geometry exists.","evidence_state":"candidate_found"}' \
  --program-summary "The candidate-generation run completed and parsed a candidate." \
  --mechanism-summary "The result is candidate evidence only, not a validated TS." \
  --implication "Run TS/Freq validation on this candidate." \
  --next-branch "Start a TS/Freq validation node."
```

`end_node` updates:

- `node.json`
- `tree.json`
- `evidence_registry.json`
- `reflection.md`
- `knowledge_base.md`
- `mechanism_model.json` when mechanism analysis is present
- accepted-state manifest fields when the accepted audit gates pass

`Success` maps to the phase-level internal claim. `Error` maps to a program or
runtime failure without a scientific conclusion. `Stopped` maps to an
administrative stop. The mechanism implication always belongs in
`closure_explanation`, not in a separate top-level mechanism status enum.

## Report And Decision Validation

`report_workspace` is read-only:

```bash
python scripts/ts_workspace.py report_workspace --root tssearch_example --pretty
```

The report includes an `allowed_response_contract`. The model should use it to
build a proposed action JSON, then the caller should validate that JSON:

```bash
python scripts/ts_workspace.py validate_decision \
  --root tssearch_example \
  --decision-file decision.json \
  --pretty
```

Only a validated decision should be translated into `start_node` or `end_node`
arguments.

## Backtracking

Backtracking is a planning decision derived from the report and closed-node
explanations. It is not a separate public mutation command.

When a branch fails:

1. Close the failed node with `end_node`.
2. Run `report_workspace`.
3. Choose the closest chemically meaningful ancestor.
4. Start the replacement node with `start_node`.
5. Record the changed variable, parent choice, and reason in the new node
   rationale.

The validator still checks tree consistency, active frontier, closed nodes, and
backtrack metadata if present.

## Pathway State

`pathway_model.json` aggregates multi-step mechanisms. Pathway state is
step-scoped:

- a candidate belongs to one elementary step;
- an accepted TS belongs to one elementary step;
- a whole pathway is complete only when every required step is accepted.

Use `--pathway-id` and `--step-id` on `start_node` and `end_node`. Do not reuse
TS/Freq or connectivity evidence from one pathway step as proof for another.

## Validation

Run:

```bash
python scripts/ts_validate_workspace.py --source tssearch_example --pretty --strict
```

The validator checks:

- required root files;
- tree/node index consistency;
- parent and input references;
- active and closed node indexes;
- evidence paths;
- closure explanation completeness;
- phase and disposition vocabulary;
- pathway references;
- accepted-state gates.
