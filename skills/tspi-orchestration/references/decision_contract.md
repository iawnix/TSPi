# Decision Contract

## Contents

- [Creating Graph Records](#creating-graph-records)
- [Recording Science](#recording-science)
- [Validation And Acceptance](#validation-and-acceptance)
- [Updating And Completing](#updating-and-completing)
- [Atomic Change](#atomic-change)

`ts_change` accepts one object with `rationale`, unique `basisRefs`, and an
ordered non-empty `operations` array. The Kernel privately compiles a
revision-bound `ts-research-decision/3`, validates the complete post-state, and
returns allocated refs only after atomic commit.

For exact fields, first query
`ts_state mode=change_contract operation=<operation>`. This on-demand catalog is
generated from the same registry used by the compiler, so the always-present
tool schema can remain small without making callers guess operation fields.
When an operation has variants, the catalog lists each variant's required and
optional fields and its matching snippet. In particular, use the
`record_observation_candidate.json` snippet for parser-owned candidates rather
than copying parser output into the direct observation form.

The change compiler allocates every technical ID. Decision IDs are
workspace-local monotonic ordinals (`dec_1`, `dec_2`, ...). Each creating
operation needs a unique `local_ref`; later operations in the same draft refer
to it as `$local_ref`.

All canonical research records use workspace-local monotonic ordinals:
`phase_1`, `claim_1`, `rel_1`, `node_1`, `obs_1`, `fnd_1`, `proof_1`, `result_1`, `acc_1`,
`gate_1`, and `gate_result_1`, and so on. Allocation, dry-run validation, and commit share one workspace lock, so
callers never hold or copy an uncommitted Decision. Committed, aborted, and
recoverable Decision transaction IDs are not reused.

## Creating Graph Records

- `create_phase`: human-facing title and objective. It groups Nodes but carries
  no lifecycle or policy.
- `create_claim`: `question`, `claimType`, `statement`, `scope`,
  `uncertainty`, `predictions`, and `falsifiers`; optional assumptions, tags,
  and creator Node. Predictions and falsifiers are required pre-registration,
  not fields to be inferred after a result is observed.
- `relate_claims`: source/target Claim refs, open relation type, and rationale.
- `start_node`: required Phase, title, objective, deliverable, optional
  dependency refs, primary/additional Claim refs, and tags.

Node dependencies may cite several earlier Nodes. They express provenance, not a
required order or permission.

One Decision may create at most one Phase, start at most one Node, and complete
at most one Node. It may start and complete that same Node. If it closes an
existing Node while opening another, the new Node must explicitly depend on the
completed Node; unrelated or parallel transitions use separate Decisions.

## Recording Science

- `record_observation`: producing Node, semantic `conceptId`, `subjectRef`, typed
  value, optional unit/qualifiers, summary, verified artifact ID/digest pairs,
  and producer provenance.
- `record_finding`: open finding type, severity, statement, and applicable
  Claim/Node/Observation refs.
- `resolve_finding`: terminal status, summary, and optional resolving
  Observation refs.

Do not provide producer-specific parser blobs when the validation engine needs
distinct concepts. Omit artifacts only for a genuine explicit observation that
has no file source.

## Validation And Acceptance

- `freeze_proof_spec`: producing Node, target Claim, open dimension, title,
  and exactly one packaged template binding or declarative definition.
- `evaluate_proof`: producing Node, frozen spec ref, and explicit selected
  Observation refs.
- `accept_claim`: target Claim, versioned profile, summary, and a local ref for
  the acceptance record.

`freeze_gate` accepts `scope=node|claim`, a target ref, and a versioned Gate
profile. It freezes an immutable `GateSpec` in `gate_specs.json`. `evaluate_gate`
references that spec, evaluates the installed deterministic predicates against
the current scientific revision, and writes a digest-bound `GateResult` to
`gate_results.json`. A later state revision makes an older result stale; it is
history, not a new verdict for the current state. Neither Gate operation changes
Claim status or selects a successor Node.

ProofSpec/ValidationResult remain the ClaimGate's evidence dimensions, and
NodeGate remains the Node completion guard. The compatibility projection is used
when no explicit Gate registry exists.

Compilation expands templates and freezes digests before commit. Evaluation is
deterministic against the proposed state, so one change may record Observations,
freeze a specification, and evaluate it using local aliases in one atomic
request.

Acceptance requires a supported Claim and at least one attached ProofSpec. It
uses all attached ProofSpecs and the latest result for each, then fails if
coverage, required dimensions, passing verdicts, digests, or blocking Finding
policy do not hold. The resulting file is immutable history; currentness is a
derived comparison against later canonical state.

## Updating And Completing

- `update_claim`: target, new status, cited summary, Observation refs, and
  ValidationResult refs.
- `complete_node`: target, outcome `completed|inconclusive|blocked|stopped`,
  summary, and open questions.
- `set_focus`: current focus Claim and Node refs. When a newly opened Node is
  the active work item, include this operation in the same Decision (unless the
  rationale explicitly preserves another focus).

Completing a Node does not infer Claim status or acceptance. When an explicit
NodeGate exists, completion additionally requires its latest matching
`GateResult.verdict=pass`. Updating a Claim does not complete a Node. Deterministic activities are derived from journaled
`node_refs`; never add a Decision solely to link an operation. Completion fails
while an owned Compute run or deterministic activity is non-terminal, an owned
activity journal is inconsistent, a compute control is pending/unresolved, or
an owned calculation Attempt has not settled. `submitted`, `queued`, `running`,
`completed`, `collected`, `missing`, `unknown`, and invalid Attempt records block
completion; `completed` is a scheduler/program outcome, not a parsed result.
Created/prepared intents have no external effect and may be abandoned. A
terminal failed activity can close the Node as `inconclusive`, `blocked`, or
`stopped`, but not as `completed`. Pure analytical Nodes need no activity record.

If an older release already closed a Node before its Attempt settled, preserve
that history. Continue `inspect`/`finalize` with the Attempt's original Node and
intent identity; do not move the Attempt or reopen the Node. Record the verified
scientific result from an open dependent recovery Node using normal artifact
ID/SHA-256 bindings. Parser-candidate promotion is same-Node only, so a recovery
Node records the independently verified value directly rather than rebinding a
candidate generated under the closed Node.

## Atomic Change

1. Read the smallest useful `ts_state` projection.
2. Submit one complete `ts_change` request with rationale and local aliases.
3. Use returned allocated refs or read a fresh delta/frontier projection.

The Kernel compiles, checks revision binding, applies to an isolated copy,
validates the complete post-state, and commits while holding one workspace lock.
A successful Review awaiting Root response blocks mutation. A failed change
does not expose a partially compiled Decision or mutate canonical state.

Examples under `assets/templates/decision/` are individual operation snippets
for the `ts_change.operations` array. They are not a prescribed research sequence.
