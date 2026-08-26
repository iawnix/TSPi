# Decision Contract

`ts_workspace_decision_draft` accepts one object with `rationale`, unique
`basis_refs`, and an ordered non-empty `operations` array. It returns a complete
revision-bound `ts-research-decision/2` plus `allocated_refs`.

The draft endpoint allocates every technical ID. Decision IDs are
workspace-local monotonic ordinals (`dec_1`, `dec_2`, ...). Each creating
operation needs a unique `local_ref`; later operations in the same draft refer
to it as `$local_ref`.

All canonical research records use workspace-local monotonic ordinals:
`phase_1`, `claim_1`, `rel_1`, `node_1`, `obs_1`, `fnd_1`, `gsp_1`, `val_1`, `acc_1`, and
so on. Concurrent drafts from the same revision can propose the same next IDs.
Drafting does not reserve them. The first Decision to commit owns its Decision
ID and canonical changes; exact content can replay idempotently, while
conflicting content or stale allocations must be redrafted. Committed, aborted,
and recoverable Decision transaction IDs are not reused.

## Creating Graph Records

- `create_phase`: human-facing title and objective. It groups Nodes but carries
  no lifecycle or policy.
- `create_claim`: `claimType`, `statement`, optional assumptions, falsifiers,
  tags, and optional creator Node.
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

- `freeze_validation_spec`: producing Node, target Claim, open dimension, title,
  and exactly one packaged template binding or declarative definition.
- `evaluate_validation`: producing Node, frozen spec ref, and explicit selected
  Observation refs.
- `accept_claim`: target Claim, versioned profile, summary, and a local ref for
  the acceptance record.

Compilation expands templates and freezes digests during draft. Evaluation is
deterministic against the draft state, so a Decision may record Observations,
freeze a specification, and evaluate it using local aliases in one atomic
request.

Acceptance requires a supported Claim and at least one attached GateSpec. It
uses all attached GateSpecs and the latest result for each, then fails if
coverage, required dimensions, passing verdicts, digests, or blocking Finding
policy do not hold. The resulting file is immutable history; currentness is a
derived comparison against later canonical state.

## Updating And Completing

- `update_claim`: target, new status, cited summary, Observation refs, and
  ValidationResult refs.
- `complete_node`: target, outcome `completed|inconclusive|blocked|stopped`,
  summary, and open questions.
- `set_focus`: current focus Claim and Node refs.

Completing a Node does not infer Claim status or acceptance. Updating a Claim
does not complete a Node. Deterministic activities are derived from journaled
`node_refs`; never add a Decision solely to link an operation. Completion fails
while an owned Compute run or deterministic activity is non-terminal, an owned
activity journal is inconsistent, or a compute control is pending/unresolved. A
terminal failed activity can close the Node as `inconclusive`, `blocked`, or
`stopped`, but not as `completed`. Pure analytical Nodes need no activity record.

## Three-Step Commit

1. Draft once and retain the returned Decision unchanged.
2. Validate the exact Decision with `ts_workspace_decision_validate`.
3. Apply that exact Decision with `ts_workspace_decision_apply`.

Apply repeats revision binding and complete post-state validation under the
workspace lock. A successful Review awaiting Root disposition blocks mutation.
A stale Decision must be redrafted, not patched.

Examples under `assets/templates/decision/` are individual operation snippets
for the draft `operations` array. They are not a prescribed research sequence.
