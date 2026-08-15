# Decision Contract

`ts_workspace_decision_draft` accepts one object with `rationale`, unique
`basis_refs`, and an ordered non-empty `operations` array. It returns a complete
revision-bound `ts-research-decision/1` plus `allocated_refs`.

The draft endpoint allocates every technical ID. Each creating operation needs
a unique `local_ref`; later operations in the same draft refer to it as
`$local_ref`.

## Creating Graph Records

- `create_claim`: `claimType`, `statement`, optional assumptions, falsifiers,
  tags, and optional creator Act.
- `relate_claims`: source/target Claim refs, open relation type, and rationale.
- `start_act`: objective, optional dependency/Claim refs, hypothesis package,
  and tags.

Act dependencies may cite several earlier Acts. They express provenance, not a
required order or permission.

## Recording Science

- `record_observation`: producing Act, semantic `conceptId`, `subjectRef`, typed
  value, optional unit/qualifiers, summary, verified artifact ID/digest pairs,
  and producer provenance.
- `record_finding`: open finding type, severity, statement, and applicable
  Claim/Act/Observation refs.
- `resolve_finding`: terminal status, summary, and optional resolving
  Observation refs.

Do not provide producer-specific parser blobs when the validation engine needs
distinct concepts. Omit artifacts only for a genuine explicit observation that
has no file source.

## Validation And Acceptance

- `freeze_validation_spec`: producing Act, target Claim, open dimension, title,
  and exactly one packaged template binding or declarative definition.
- `evaluate_validation`: producing Act, frozen spec ref, and explicit selected
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
- `complete_act`: target, outcome `completed|inconclusive|blocked|stopped`,
  summary, and open questions.
- `set_focus`: current focus Claim and Act refs.
- `link_operation`: Act plus immutable deterministic operation ref.

Completing an Act does not infer Claim status or acceptance. Updating a Claim
does not complete an Act. Keep each assertion explicit and cited.

## Three-Step Commit

1. Draft once and retain the returned Decision unchanged.
2. Validate the exact Decision with `ts_workspace_decision_validate`.
3. Apply that exact Decision with `ts_workspace_decision_apply`.

Apply repeats revision binding and complete post-state validation under the
workspace lock. A successful Review awaiting Root disposition blocks mutation.
A stale Decision must be redrafted, not patched.

Examples under `assets/templates/decision/` are individual operation snippets
for the draft `operations` array. They are not a prescribed research sequence.
