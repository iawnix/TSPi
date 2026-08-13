# Agent Decision Protocol

The Root Agent chooses research direction. `ts_workspace` validates state,
evidence references, authority, and topology; it does not select the next node.

## Decision Loop

1. Read `report_workspace` or `ts_workspace_context`.
2. Name the active hypothesis and prediction.
3. State the highest evidence layer actually supported.
4. Identify the discriminator that could change the hypothesis status.
5. Load only relevant historical node or branch context.
6. Choose one research act and one branch relation.
7. Construct and validate `ts-decision/2` against the current revision.
8. Apply one mutation.

Program success, parser output, subagent advice, and visual inspection are inputs
to this decision, not decisions themselves.

## Choosing A Node Type

- New user inputs or missing constraints: `intake` (`n000` only for a new
  workspace; ask the user rather than reopening intake later).
- Propose, compare, revise, or evaluate a hypothesis: `mechanism`.
- Generate structures without testing TS validity: `candidate_search`.
- Produce a declared test: `validation` with the matching scope.
- Decide acceptance or completion from registered evidence: `audit`.

Wavefunction, population, orbital, spin, or state analysis is a validation act,
normally `electronic_structure` or `state_character`. It does not directly set
hypothesis status. Open a later mechanism evaluation node.

## Evidence Before Status

- `program.outcome=success` means the operation completed.
- `hypothesis.status=unsupported` requires a contradicted prediction or
  explicit decision boundary.
- Missing or conflicting evidence is `ambiguous`.
- `audit.status=accepted` means the audited object passed its declared gates.
- A pathway audit can be `not_accepted` while the overall study remains open.

For a pathway audit, the running node must already have `node.pathway_ref`.
Before closure, register a pathway audit record with
`quality.strict_pathway_decision=accepted` or
`quality.strict_pathway_decision=pathway_not_accepted` and cite it in the close
decision.

## Previous Failed Exploration

A previous failed exploration affects the next decision only after its scope is
checked.

Read:

- `report_workspace.node_index` for candidate checkpoints;
- `nodes/<failed_node>/node.json` through `report_node`, not direct prompt
  injection;
- `report_branch_context(from_node, anchor_node)` for the trigger, selected
  checkpoint, and attempts between them;
- registered evidence and local attempt artifacts for the failure cause.

Classify the failure:

- program failure: scheduler, executable, SCF, optimizer, parser, scratch,
  transfer, or timeout;
- candidate failure: structure does not provide a useful TS seed;
- validation contradiction: evidence conflicts with a prediction;
- audit blocker: required evidence is missing or inconsistent;
- scope mismatch: the old result tests another hypothesis, pathway, charge,
  multiplicity, state, or method boundary.

Do not reopen or rewrite the failed node. Decide whether to retry an attempt,
recalculate, continue, branch from a historical anchor, revise the hypothesis,
ask the user, or stop.

Across independent repeated studies, a historical failure is a prior, not a
workspace fact, until its structures, method, scope, and artifacts are verified
for the current study.

## Branch Relations

### `continue_parent`

Use when the same scientific object proceeds to another evidence act. The new
node's parent is `from_node`.

### `new_solution_branch`

Use when the hypothesis is retained but the candidate or search strategy
changes. Select an ancestor checkpoint after loading it. The new parent is the
anchor; the failed trigger remains `from_node`. Bind the replacement candidate
or strategy with a new `solution_ref.solution_id`; use `parent_solution_id` when
the source solution already has an explicit identity.

### `new_hypothesis_branch`

Use for an alternative mechanism proposal with a new hypothesis ID and a known
parent hypothesis. The proposal itself is a `mechanism/propose` node.

### `new_pathway_branch`

Use when elementary-step decomposition, intermediate topology, or pathway
assignment changes. Bind a pathway ID not already declared by the workspace and
retain the source hypothesis. The node, tree index, and branch event must expose
the same target pathway reference.

### `recalculation_of`

Use only for a scientifically meaningful method change that receives a new
research node. A technical retry stays under the existing node as
`ts-calculation-intent/2 attempt_kind=retry`.

## Backtracking

Backtracking means:

1. select `from_node` as the current trigger;
2. select an ancestor `anchor_node` whose scientific state remains usable;
3. inspect `report_branch_context`;
4. create a new node parented to the anchor with the chosen relation;
5. preserve all failed descendants as history.

The validator checks ancestry and references. It cannot decide which anchor is
scientifically useful.

If an older closed `new_solution_branch` lacks its required solution identity,
do not edit canonical JSON. Submit one `repair_solution_ref` decision after
selecting a new solution ID and explaining the historical defect. This is a
metadata repair only; it neither reopens the node nor changes its scientific
closure.

## Subagent Use

Use independent review only when it may change a decision: competing
hypotheses, ambiguous validation, conflicting evidence, failure diagnosis,
backtrack selection, or audit readiness. The result is advisory and cannot be
registered as primary evidence without independent local artifact support.

## Decision Templates

`assets/templates/decision/` contains minimal `ts-decision/2` examples. Build
workspace-specific decisions from `references/decision_contract.md` or the Pi
four-tool control plane, then validate before applying.
