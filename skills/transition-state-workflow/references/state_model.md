# State Model

New research uses `ts-node/2`. A node is one bounded research act, not one turn,
one remote job, or a mandatory pipeline stage.

## Node Types

- `intake`: `n000` only. Normalize user input, structures, constraints, and
  completion criteria.
- `mechanism`: propose, compare, revise, or evaluate a hypothesis.
- `candidate_search`: generate a transition-state, endpoint-conformer,
  intermediate, or crossing-point candidate.
- `validation`: produce evidence for one declared prediction and scope.
- `audit`: audit a transition state, elementary step, pathway, or complete
  study.

Validation scopes:

- `tsfreq`
- `connectivity`
- `electronic_structure`
- `state_character`
- `thermochemistry`
- `method_robustness`
- `geometry_identity`

Frequency and connectivity/IRC are distinct evidence gates even though both
use `node_type=validation`.

## Independent State Axes

`node.lifecycle`:

- `running`
- `closed`
- `stopped`

`closure.program.outcome`:

- `success`
- `failure`
- `not_run`

`closure.hypothesis.status`, mechanism nodes only:

- `supported`
- `unsupported`
- `ambiguous`

`closure.audit.status`, audit nodes only:

- `accepted`
- `not_accepted`
- `ambiguous`

Missing, weak, or conflicting evidence is `ambiguous`. `unsupported` requires a
declared prediction or decision boundary to be contradicted. Program failure
does not evaluate a hypothesis.

Candidate and validation nodes cannot write hypothesis or audit status. Their
closures contain program facts and evidence references. A later mechanism node
interprets whether those facts support or falsify the hypothesis.

## Hypotheses

The initial hypothesis is created by a `mechanism` node with
`mechanism_action=propose` and `proposed_hypothesis`. Alternative hypotheses use
another mechanism proposal node and `relation=new_hypothesis_branch`.

Prediction objects declare `validation_scope`, expected observation, and
required evidence roles. A validation node must cite prediction IDs whose scope
matches the node.

## Recalculation

Recalculation is not a node type.

- Technical retry: a new calculation attempt under the same node with
  `attempt_kind=retry`.
- Scientifically meaningful method change: a new node of the same scientific
  type with `attempt_kind=recalculation`, `recalculation_ref`, and
  `branch_context.relation=recalculation_of`.

The recalculation relation records the source node or intent, changed settings,
and purpose (`repair`, `refinement`, or `method_robustness`). It does not copy a
scientific verdict.

## Branches And Backtracking

Every post-`n000` node records one relation:

- `continue_parent`
- `new_solution_branch`
- `new_hypothesis_branch`
- `new_pathway_branch`
- `recalculation_of`

`from_node` is the trigger. `anchor_node` is the historical checkpoint selected
by the Root Agent. Backtracking creates a new child from the anchor; it never
rewrites historical nodes.

Use `report_node` and `report_branch_context` to load only the relevant history
before selecting an anchor.

Only `ts-node/2` records are valid workspace nodes. The validator rejects
phase-based nodes and old closure fields rather than converting them.
