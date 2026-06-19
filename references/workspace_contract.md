# Chemistry Hypothesis Workspace

This workspace is the durable ledger for transition-state exploration. It
tracks mechanism hypotheses, node-level program evidence, mechanism
interpretation, and the constraints used to choose the next branch.

The public control plane has six commands:

```bash
python scripts/ts_workspace.py init_workspace --root <tssearch_root> ...
python scripts/ts_workspace.py start_node --root <tssearch_root> ...
python scripts/ts_workspace.py end_node --root <tssearch_root> ...
python scripts/ts_workspace.py report_workspace --root <tssearch_root> --pretty
python scripts/ts_workspace.py validate_decision --root <tssearch_root> --decision-file decision.json --pretty
python scripts/ts_workspace.py validate_workspace --root <tssearch_root> --pretty
```

Do not use older workspace subcommands or wrapper scripts as a public
interface.

## Required Root Files

`init_workspace` creates these required structures:

- `knowledge_base.md`: validated facts, rejected hypotheses, open questions,
  and next-decision notes.
- `manifest.json`: workspace identity, charge, multiplicity, root path,
  accepted-state audit fields, and schema identifiers.
- `mechanism_model.json`: mechanism hypotheses, required diagnostics, and
  evidence-backed mechanism analysis records.
- `pathway_model.json`: optional pathway and elementary-step aggregation.
- `tree.json`: node index, parent/child relationships, active frontier, closed
  nodes, accepted nodes, and timeline events.
- `evidence_registry.json`: evidence records referenced by closed nodes and
  mechanism analysis.
- root directories `inputs/`, `nodes/`, `reports/`, `accepted/`, and
  `rejected/`.

The workspace also contains `nodes/<node_id>/` directories. A node directory
may hold:

- `node.json`: structured node record.
- `decision_card.md`: generated human-readable rationale for the node.
- `reflection.md`: closure reflection after `end_node`.
- `inputs/`, `outputs/`, `parsed/`, `scratch/`: node-scoped runtime and parsed
  artifacts.

## Public Node State

The LLM-facing state is intentionally small:

- `phase`: `preflight`, `endpoint`, `rp_conformer_generation`,
  `candidate_generation`, `tsfreq_validation`, `connectivity_validation`, or
  `accepted_audit`. Use `pathway_audit` only for a pathway-level audit that
  aggregates already accepted elementary-step TS nodes.
- `node_disposition`: `Running`, `Stopped`, `Error`, or `Success`.

`Running` is produced by `start_node`. `Stopped`, `Error`, and `Success` are
produced by `end_node`.

Program/runtime failures and mechanism interpretation are separated inside
`closure_explanation`:

```json
{
  "program": {
    "summary": "The Gaussian job terminated before producing a parsed frequency summary.",
    "facts": [
      {
        "text": "The output ended with an SCF convergence error.",
        "source_path": "nodes/n020_tsfreq/outputs/tsfreq.out"
      }
    ]
  },
  "mechanism": {
    "summary": "No TS/Freq conclusion can be drawn from this failed program run.",
    "facts": [
      {
        "text": "The failure does not refute the bond-switching mechanism by itself."
      }
    ]
  },
  "implication": "Open a revised TS/Freq node with changed SCF controls.",
  "open_questions": [
    "Does the candidate remain stable after a lower-level cleanup?"
  ]
}
```

Stored `node.json` files must not persist old top-level audit state fields such
as `claim_status`, `outcome`, `outcome_code`, `lifecycle_state`, `run_state`,
or `claim_level`. Validators, normalizers, and the explorer derive those audit
views from `phase`, `node_disposition`, evidence records, and
`closure_explanation`. These derived names are not LLM response fields and must
not be requested from the model.

## Workspace Lifecycle

1. Initialize:

```bash
python scripts/ts_workspace.py init_workspace \
  --root tssearch_example \
  --system example \
  --charge 0 \
  --multiplicity 1 \
  --reaction-class bond_switch \
  --bond-change breaking:C1-H2 \
  --bond-change forming:H2-O3
```

2. Read context before deciding:

```bash
python scripts/ts_workspace.py report_workspace --root tssearch_example --pretty
```

The report includes:

- `current_phase`
- `current_phase_scope`
- `current_phase_reasons`
- `focus`
- `claim_readiness`
- `available_commands`
- public node summaries
- validation summary
- context items
- endpoint evidence blockers
- open questions
- `allowed_response_contract`

`current_phase` is an attention anchor for the current scientific layer, not a
route decision. `claim_readiness` is the primary evidence diagnostic.
`blocking_gates`, `allowed_next_actions`, and `forbidden_next_actions` are not
part of the report contract.

3. Validate the next decision:

```bash
python scripts/ts_workspace.py validate_decision \
  --root tssearch_example \
  --decision-file decision.json \
  --pretty
```

4. Start a node:

```bash
python scripts/ts_workspace.py start_node \
  --root tssearch_example \
  --node-id n010_endpoint \
  --phase endpoint \
  --operation endpoint-opt \
  --hypothesis "Reactant and product references are distinct minima." \
  --rationale "Endpoint stability gates candidate generation." \
  --expected-evidence "optimized endpoint summary" \
  --refutation-criteria "reactant/product collapse or wrong reaction center" \
  --cost-risk "low-cost endpoint optimization"
```

For a replacement branch after a failed or ambiguous sibling, keep the same
public command and add backtrack provenance:

```bash
python scripts/ts_workspace.py start_node \
  --root tssearch_example \
  --node-id n031_cartesian_qst2 \
  --phase candidate_generation \
  --operation gaussian-qst2-cartesian \
  --parent-id n020_endpoint_pair \
  --replaces-node n030_default_qst2 \
  --backtrack-reason-code replacement_branch_coordinate_handling \
  --backtrack-reason "Default internal-coordinate QST2 failed before chemistry evidence; Cartesian QST2 changes only coordinate handling." \
  --hypothesis "Cartesian QST2 can generate the same mapped H-transfer candidate." \
  --rationale "The parent endpoint pair remains valid and the changed variable is coordinate handling." \
  --expected-evidence "Gaussian candidate or TS/Freq output" \
  --refutation-criteria "Gaussian setup fails again or the reaction center changes"
```

5. Close a node:

```bash
python scripts/ts_workspace.py end_node \
  --root tssearch_example \
  --node-id n010_endpoint \
  --node-disposition Success \
  --phase endpoint \
  --decision prepare_candidate_generation \
  --summary "Endpoint references remain distinct minima." \
  --primary-file nodes/n010_endpoint/parsed/endpoint_summary.json \
  --evidence '{"kind":"endpoint_summary","path":"nodes/n010_endpoint/parsed/endpoint_summary.json","claim":"Endpoint references are ready.","evidence_state":"supports"}' \
  --program-summary "Both endpoint optimizations converged and parsed summaries were produced." \
  --program-fact '{"text":"The parsed endpoint summary reports distinct minima.","source_path":"nodes/n010_endpoint/parsed/endpoint_summary.json"}' \
  --mechanism-summary "Endpoint readiness supports candidate generation but is not a TS proof." \
  --mechanism-fact "No accepted transition state is implied by endpoint readiness alone." \
  --implication "Candidate generation may begin." \
  --next-branch "Run a candidate-generation node."
```

## Decision Payload Contract

The LLM should produce one action at a time. The allowed actions are:

- `start_node`
- `end_node`
- `ask_user`
- `stop`

Required fields for `start_node`:

```json
{
  "action": "start_node",
  "node_id": "n020_candidate",
  "phase": "candidate_generation",
  "operation": "xtb-neb-screen",
  "hypothesis": "Endpoint-ready references can generate a TS candidate.",
  "rationale": "Candidate generation is the next gated phase.",
  "expected_evidence": ["candidate geometry", "parsed candidate summary"]
}
```

Required fields for `end_node`:

```json
{
  "action": "end_node",
  "node_id": "n020_candidate",
  "node_disposition": "Error",
  "phase": "candidate_generation",
  "closure_explanation": {
    "program": {
      "summary": "The candidate-generation program failed before producing a candidate."
    },
    "mechanism": {
      "summary": "The failed program run does not refute the mechanism."
    },
    "implication": "Open a revised candidate-generation node with changed runtime inputs."
  }
}
```

Forbidden model-return fields include internal audit names such as
`claim_status`, `claim_level`, `outcome`, `outcome_code`, `lifecycle_state`,
`run_state`, and `accepted_ts`.

## Evidence Rules

- Evidence paths must be workspace-relative and point to node-scoped files when
  possible.
- Each closed node should include evidence records through `end_node`.
- Program facts should cite logs, parsed JSON, geometry files, or command
  metadata.
- Mechanism facts should cite available structural, electronic, orbital, spin,
  or energy diagnostics when those diagnostics exist.
- Do not infer missing electronic, orbital, or barrier information from a
  geometry-only or failed program result.

## Mechanism Interpretation

Mechanism analysis must distinguish these layers:

- reaction type;
- reaction-center motion;
- electronic/spin/charge diagnostics;
- orbital or population descriptors;
- energy and barrier implications.

Read `references/mechanism_analysis_sources.md` before deciding which method
can support each layer. If a layer is unavailable, say it is unavailable rather
than inferring it.

## Branching And Backtracking

Backtracking is now represented as a planning interpretation, not a separate
public command. Use `report_workspace` to identify the failed or ambiguous
node, then open the next branch with `start_node` only after making the changed
variable explicit.

A replacement branch should record:

- the parent node that remains chemically meaningful;
- the failed or ambiguous node that motivated the change, when relevant;
- the changed variable or mechanism boundary;
- the evidence or closure explanation that justifies the change.

Do not continue below an errored node unless the hypothesis has explicitly
changed and the new branch records that change.

## Pathways

For multi-step pathways, `pathway_model.json` stores pathway and elementary-step
state. Use `--pathway-id` and `--step-id` on `start_node` and `end_node` for
step-scoped nodes. A TS acceptance remains an elementary-step conclusion, not a
whole-pathway conclusion unless every required step is accepted.

Candidate, ambiguous, rejected, and accepted step statuses are derived from
step-scoped node closures and evidence gates. Do not reuse a previous step's
TS/Freq or connectivity evidence as proof for a later step.

## Validation And Explorer

Run the validator before trusting the explorer or reporting a final state:

```bash
python scripts/ts_workspace.py validate_workspace --root tssearch_example --pretty --strict
```

Generate the explorer-normalized view with:

```bash
python scripts/ts_normalize_view.py --source tssearch_example --pretty
```

The explorer is read-only. It renders normalized state from the workspace and
does not own the state vocabulary.
