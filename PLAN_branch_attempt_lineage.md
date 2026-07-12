# PLAN: Branch/Attempt Lineage And Control-Plane Baseline

## Updated Conclusion

Do not add new decision fields for the `n025/n026/n027` class of problem or for
the broader `branch_context.anchor_node` overloading noted in
`/home/iaw/TS/.TODO.md` (line 276-280). Schema growth would harden the skill
over time: every new field must be carried by validator, templates, report,
web, and legacy-workspace compatibility indefinitely.

Semantic distinctions that would otherwise require new fields are carried by
three lighter mechanisms instead:

- validator warnings that fire only on real failure signatures;
- runtime templates named by scenario, not by phase alone;
- `evidence_registry.json` role additions (evidence roles grow naturally,
  decision schema does not).

The fix is also **not** docs-first alone. Documentation clarifications ride on
top of a control-plane baseline that closes three unresolved risks in the
workspace (from `/home/iaw/TS/.TODO.md` line 282-286):

- `init_workspace` silently overwrites existing state;
- multi-file mutations in `end_node` have no transaction boundary;
- `decision_log.jsonl` and other append writes are not `fsync`ed and store
  only `payload_hash`, not the full decision.

Without those baseline fixes, semantic docs become brittle: any half-committed
mutation or lost decision can reintroduce the exact classification errors this
plan is meant to prevent.

## Phased Fix Roadmap

Each phase is independently shippable. P0 is a prerequisite for P2 landing
cleanly; P1 can run in parallel with P2.

### P0 — Control-plane safety baseline

Zero semantic change. Ships first.

- **P0-1** `init_workspace` refuses to overwrite an initialized workspace by
  default. Location: `ts_workspace/engine.py:16`. If any `REQUIRED_FILES` entry
  exists and is non-empty, raise `ContractError`. Add an explicit `--force`
  CLI flag for genuine reinitialization.
- **P0-2** Persist a full decision snapshot on every mutation. Location:
  `ts_workspace/engine.py:252` (`_log_decision`). Write
  `decisions/<decision_id>.json` and record `snapshot_ref` inside the
  `decision_log.jsonl` row. Add `decisions/` to
  `references/workspace_contract.md` required directories.
- **P0-3** `append_jsonl` and `append_markdown` must `flush()` + `os.fsync()`
  before returning. Location: `ts_workspace/io.py:37` and `io.py:44`.

### P1 — `end_node` transaction + read/write boundary

- **P1-1** Rewrite `ts_workspace/finalizers/node.py` so each finalizer returns
  `dict[Path, Any]` (a set of proposed writes) rather than calling
  `write_json` directly. This makes the mutation set inspectable before commit
  and simplifies unit tests.
- **P1-2** `end_node` computes the full proposed change set, runs all
  validators over it, records `{decision_id, stage: "prepare", paths}` in
  `transaction_log.jsonl`, applies every `write_json` (already atomic), then
  records `{decision_id, stage: "committed"}`. `validate_workspace` reports
  `pending_transaction` when a `prepare` entry has no matching `committed`
  entry; recovery is `--replay <decision_id>` from the P0-2 snapshot.
- **P1-3** `report_workspace` becomes pure read: `readers/report.py:66` must
  not `write_json`. The write path moves to an explicit `snapshot_report`
  command (or `report_workspace --write-report`). `SKILL.md` "Public Control
  Plane" splits into "Mutation CLI" (`init_workspace`, `start_node`,
  `update_workspace`, `end_node`) and "Read/Support CLI" (`report_workspace`,
  `validate_decision`, `validate_workspace`, `snapshot_report`).

### P2 — Branch semantics, templates, evidence roles, validator warnings

Docs, templates, evidence roles, and soft-warning validator rules land
together. No decision schema change.

- **P2-1 Docs.** Update `SKILL.md`, `references/decision_contract.md`,
  `references/state_model.md`, `references/workspace_contract.md` with the
  branch relation semantics and decision field boundary rules below. Insert
  an **Authority Model** section in `SKILL.md` between "Module Boundaries"
  and "Public Control Plane" that codifies the code/docs split: workspace
  enforces evidence integrity, atomicity, and provenance; route selection,
  retry vs. reformulate, and hypothesis switching are agent decisions
  guided by references and templates, not validators. A rule is code only
  if violating it corrupts state later reads cannot recover from; otherwise
  it is a template default, a validator warning, or a reference heuristic.
  Generic patterns live in the skill; project-specific priors live in the
  project's own `.TODO.md` or README.
- **P2-2 Templates.** Split scenario-specific templates so the file name
  encodes the intent:
  - `templates/decision/start_connectivity_validation__initial.json`
  - `templates/decision/start_connectivity_validation__protocol_variant.json`
    (pre-fills `branch_context.relation = continue_parent`)
  - `templates/decision/start_solution_branch__strategy_change.json`
    (the existing solution-branch template, renamed and scoped to real
    candidate/search-strategy changes)
  - Update `templates/decision/README.md` to state explicitly: "IRC parameter
    changes for the same TS/Freq claim are `continue_parent`, not
    `new_solution_branch`."
- **P2-3 Evidence role.** Add `previous_attempt_summary` to the evidence role
  whitelist. Convention: when a node continues after a failed attempt,
  `branch_context.evidence_refs` must include at least one evidence with role
  `previous_attempt_summary` pointing to the failed node's closure facts.
  Report reader can then answer "what did n027 retry?" as a single lookup,
  without grepping `reason_code` text and without any decision schema field.
- **P2-4 Validator soft warnings.** Add to
  `ts_workspace.validators`, all emitted as `warnings[]`, never `errors[]`:
  - `suspicious_new_solution_branch_for_protocol_variant`: fires when
    `relation = new_solution_branch`, `phase = connectivity_validation`, and
    `changed_variable` matches `^irc_.*|^integrator|^step_size|^corrector`.
  - `program_failure_used_as_new_solution_branch`: fires when
    `relation = new_solution_branch` and `reason_code` matches
    `.*convergence_failed|scheduler_failure|parser_failure`.
  - `same_claim_reused_as_new_solution_branch`: fires when
    `relation = new_solution_branch`, the same `hypothesis_ref` already has a
    supported TS/Freq node in the last 24h, and `changed_variable` contains
    no candidate/geometry/search token.
  - Old workspaces do not become invalid; agents get the hint on the next
    mutation.
- **P2-5 Strategy reflection reference.** Add
  `references/strategy_reflection.md` and a symptom-based trigger clause in
  `SKILL.md` References. See the dedicated section below.

## Correct Use Of Existing Fields

For a same-claim validation protocol variant (the n025/n026/n027 shape), the
existing fields express the intent without any schema change:

```json
{
  "parent_node": "n025",
  "phase": "connectivity_validation",
  "hypothesis_ref": {
    "hypothesis_id": "hyp_0004",
    "prediction_ids": ["pred_uv_conn_001"]
  },
  "branch_context": {
    "relation": "continue_parent",
    "from_node": "n025",
    "anchor_node": "n020",
    "changed_variable": "irc_integration_settings",
    "reason_code": "n026_irc_corrector_convergence_failed",
    "evidence_refs": [
      "ev_edaa_n026_irc_endpoint_assignment",
      "ev_edaa_n026_connectivity_gate",
      "ev_edaa_n026_previous_attempt_summary"
    ]
  }
}
```

`continue_parent` requires `parent_node == branch_context.from_node`. The
failed attempt node `n026` is therefore not `from_node`; it is captured by
`reason_code`, rationale, closure facts, and the P2-3
`previous_attempt_summary` evidence entry.

Consumed upstream artifacts continue to be recorded in
`nodes/<node>/outputs/artifact_manifest.json`, not by adding decision fields.

## Branch Relation Semantics To Document

### `continue_parent`

Use when the new node continues from the same scientific object or claim.

Typical cases:

- candidate → TS/Freq validation;
- TS/Freq-supported node → connectivity validation;
- connectivity validation → accepted audit;
- accepted audit → pathway audit;
- a same-claim validation protocol variant, e.g. a second IRC attempt from
  the same TS/Freq-supported checkpoint.

Rules:

- `payload.parent_node == payload.branch_context.from_node`.
- `anchor_node` is the source node of the active hypothesis or the stable
  branch grouping anchor.
- A previous failed program attempt can be cited via `reason_code`,
  `rationale`, and `branch_context.evidence_refs` (with role
  `previous_attempt_summary`); it does not have to be the graph parent.

### `new_solution_branch`

Use only when the agent changes the candidate/search strategy or the solution
object under the same chemical hypothesis.

Typical cases:

- QST candidate failed, open a constrained scan candidate branch;
- a TS/Freq-supported candidate was refuted by strict connectivity, so the next
  node starts a different candidate or TS-search strategy;
- the mechanism hypothesis remains viable, but the current computational
  solution branch is exhausted.

Do not use for:

- re-running or changing IRC settings for the same TS/Freq-supported claim;
- parser, scheduler, or corrector-convergence follow-up when the scientific
  object remains the same;
- simple next-layer validation.

Current validator rule remains:

- `parent_node == branch_context.anchor_node`;
- for same-hypothesis replacement solutions, `anchor_node` must be the
  hypothesis `source_node`;
- `solution_ref.solution_id` must be new when replacing a solution branch.

### `new_hypothesis_branch`

Use only when the mechanism hypothesis changes. Examples:

- direct concerted path → stepwise intermediate path;
- ground-state mechanism → UV/excited-state mechanism;
- ketone-side Wolff path → ester-side Wolff path, when treated as a distinct
  mechanism hypothesis.

### `new_pathway_branch`

Use only when pathway topology or step model changes while hypothesis handling
remains explicit. Examples:

- single-step pathway → two-step pathway with an intermediate;
- product basin / pathway step assignment changes.

### `administrative_followup`

Use for non-scientific control-plane work (monitoring handoff, report
packaging, workspace repair, visualization, diagnostic-only tasks). It must
not carry a chemistry verdict.

## Decision Field Boundary Rules

- **`phase`** — evidence layer under test; not a route label, not a success
  state.
- **`hypothesis_ref`** — the mechanism hypothesis and prediction this node
  tests. `prediction_ids` holds only the phase-level prediction under test;
  upstream supporting predictions go into `evidence_refs`.
- **`solution_ref`** — computational search-strategy lineage under a
  hypothesis. Not a verdict, retry status, lifecycle state, or branch
  relation. `solution_ref` never forces `new_solution_branch`; the branch
  relation comes from `branch_context.relation`. For same-claim protocol
  variants, `solution_ref` may be omitted.
- **`branch_context`** — graph relation and branch intent only. Answers:
  continuation, replacement solution, new hypothesis, new pathway, or
  administrative. Does not carry full artifact provenance or all failed-attempt
  history; those belong in `artifact_manifest.json`, closure facts, evidence
  records, and decision rationale.
- **`pathway_ref`** — pathway/step membership only; does not imply support,
  acceptance, or completeness.
- **`expected_evidence`** — planned evidence outputs at node start; not a
  checklist verdict.
- **`evidence_refs`** — top-level `decision.evidence_refs` records what was
  considered when making the decision; `closure.program.evidence_refs`
  supports execution facts; `closure.mechanism.evidence_refs` supports the
  scientific judgment. Do not copy every evidence id into every layer.
- **`program_status` / `claim_verdict`** — keep execution facts separate from
  scientific judgment. `program_status = failed|stopped` requires
  `claim_verdict = not_evaluated`. A normal-terminated calculation can still
  be `claim_verdict = refuted`. A `pathway_audit` with
  `claim_verdict = supported` supports the audit conclusion, not pathway
  acceptance.
- **`impact_scope`** — scopes the scientific implication of a closure
  revision: `solution_only`, `prediction`, `pathway_step`, `hypothesis`. Does
  not replace `branch_context.relation`.

## Docs, Templates, And Evidence Registry Changes

Primary docs (P2-1):

- `SKILL.md` — Workflow step 4 gains a branch relation decision table and an
  explicit warning that program failure follow-up is not automatically a new
  branch. Add the same-claim IRC retry example.
- `references/decision_contract.md` — new "Branch Relation Semantics" section
  after "Later Mechanism Nodes".
- `references/state_model.md` — extend the `solution_ref` paragraph:
  `solution_ref` does not choose branch relation; same-claim protocol changes
  stay on `continue_parent` when the scientific parent is unchanged.
- `references/workspace_contract.md` — add `decisions/` to required
  directories (from P0-2); document the P1 transaction log semantics.

Templates (P2-2): as listed above.

Evidence registry (P2-3): add `previous_attempt_summary` to the role
whitelist. Add a one-paragraph note in `references/workspace_contract.md`.

Optional example: a short same-claim IRC retry walk-through in
`references/connectivity_validation.md`.

## Strategy Reflection Reference (P2-5)

`references/strategy_reflection.md` fills a real gap between
`mechanism_reflection.md` (which reflects on whether a mechanism claim is
well-formed at claim-creation time) and `connectivity_validation.md` (which
defines what counts as a strict IRC pass). Neither answers "the same
hypothesis has now failed the same way twice — what should I reconsider?"

The document is a **heuristics library**, not a checklist and not a decision
tree. It is loaded on symptom triggers, not on every task.

### Scope discipline — what is in, what stays out

**In** (generic route/method reflection any TS task can hit):

- R/P endpoints define target basins, not the TS-search method. Do not
  default to QST2/QST3 merely because R/P endpoints are available; justify
  from atom mapping, conformer compatibility, and the elementary-step model.
- On repeated same-shape Gaussian failure (route mismatch, MaxCycle ineffective,
  parser desync), address the backend/route issue before tuning the seed.
  Continued seed micro-adjustments on an ineffective route waste the budget.
- On repeated wrong-basin IRC under the same hypothesis, question whether
  the TS type is right (soft mode, shoulder, wrong reaction coordinate)
  before continuing to search structurally similar candidates.
- For photochemistry / open-shell / non-adiabatic hypotheses, decompose the
  hypothesis by electronic surface before framing an R→P IRC. A ground-state
  R→P IRC over a mechanism that involves a crossing or excited-state channel
  is a category error, not a computational failure.
- Loose fragments (N2, CO, small ligands) placed by hand interpolation or
  ad-hoc constraint are candidates only. Before promoting to TS/Freq,
  require a constraint-release relaxation or a small scan showing the region
  is not artificially stabilized by the constraint.
- When a hypothesis admits multiple a priori plausible reaction sites or
  functional-group participants, attack the site with lower structural
  strain and stronger literature precedent first; keep the alternative as a
  checked comparator branch, not a parallel primary line.

**Out** (project-specific priors — do not go into a shared skill reference):

- Named system defaults ("for EDAA, ketone-side Wolff is primary"). These
  are project-level priors; if truly needed, keep them in the project's
  own `.TODO.md` or task README.
- Named molecule / substrate names, project acronyms, workspace roots.
- Any statement that presupposes a specific reagent, solvent, or basis set.

Enforcement rule for the document itself: **every example uses a generic
label (e.g. "diazo → ketene via carbene channel") rather than a specific
molecule; project-specific priors are cited only by category, never named.**

### Trigger clause in `SKILL.md`

Under "References", add (do not replace the existing list):

> Read `references/strategy_reflection.md` when any of the following holds:
> (a) the same `hypothesis_ref` has ≥2 consecutive nodes whose IRC endpoint
> assignments fall on the same side (product/product or reactant/reactant);
> (b) the same `hypothesis_ref` has ≥2 Gaussian route-mismatch diagnostics
> or route-ineffective closures; (c) the active
> `initial_mechanism_hypothesis.structured_claim.electronic_model` marks
> `excited_state`, `open_shell`, or `non_adiabatic`; (d) any recent
> `reason_code` matches `wrong_basin|route_ineffective|surface_ambiguous`.

The trigger is symptom-based, not "read when stuck". Detection is on fields
the workspace already exposes.

### Writing-style discipline

To keep heuristics from turning into rules:

1. Every entry ends with a **reflection question**, not a directive.
   Write "Ask: is this failure batch a single route/backend property?"
   not "Change route to X."
2. Every entry lists at least one **counter-example** where the heuristic
   does not apply.
3. The document opens with a status paragraph:

   > This file is a heuristics library, not a workflow. Hard constraints live
   > in `workspace_contract.md` and the evidence gates. Nothing in this file
   > can change `validate_workspace`, `accepted_audit`, or any verdict.

4. `references/mechanism_reflection.md` gains a one-line pointer at the top:

   > For route-level reflection after repeated same-shape failure, see
   > `strategy_reflection.md`.

## Test And Validation Plan

Run after each PR:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
npm pack --dry-run
```

Add regression coverage per phase:

- P0-1: `test_init_refuses_overwrite`, and update every existing init test to
  either start empty or pass `force=True`.
- P0-2: assert `decisions/<decision_id>.json` exists after a mutation and its
  content round-trips.
- P0-3: assert `os.fsync` is called (patch and record) or, integration-level,
  kill mid-append and verify the last row is intact.
- P1-1/P1-2: assert finalizer returns a dict, no writes on validator failure,
  `transaction_log.jsonl` has matching `prepare`/`committed` rows.
- P1-3: `report_workspace` return value is unchanged; no files created;
  `snapshot_report` creates `reports/<report_id>.json`.
- P2-2: template tests still pass; new templates validate against the
  decision schema.
- P2-3: an `evidence_registry.json` with role `previous_attempt_summary` is
  accepted; report reader can find it.
- P2-4: each warning fires only on the intended signature; none fire on
  legacy accepted workspaces (regression against `TSResearch_job049`,
  `TSResearch_job099`).
- P2-5: `references/strategy_reflection.md` exists and passes a lint that
  rejects named molecules / project acronyms / workspace-specific priors
  (e.g. grep for `EDAA`, `Wolff`, `trans1x_`, `TSResearch_` in this file
  fails the build); the `SKILL.md` trigger clause is syntactically well-formed
  and its symptom predicates reference only fields already exposed by the
  workspace contract.

## Non-Goals And Red Line For Schema Growth

Do **not**:

- add `claim_anchor_node`, `previous_attempt_node`, `artifact_source_node`,
  `hypothesis_anchor_node`, or any similar first-class field;
- add new `branch_context.relation` values (e.g.
  `continue_validation_of_same_claim`, `validation_protocol_variant`);
- change decision schema in this plan;
- auto-migrate existing workspaces;
- make validators infer chemistry or branch policy from Gaussian status;
- weaken TS/Freq, connectivity, accepted audit, or pathway audit gates.

A decision schema field is only justified when **both** of these hold:

1. The semantic distinction must be machine-queryable (evidence role +
   rationale text cannot express it), and this query already appears in at
   least two of {report, web, accepted audit, validator}.
2. The failure it prevents is unconverging under P2: after warnings +
   templates + docs + role landed, the same misclassification reappears at
   least twice within 60 days, and each recurrence required manual lineage
   repair.

Neither condition is met today. If either condition later fires, revisit —
until then, warnings and templates carry the load.

## PR Breakdown

| PR   | Scope                              | Depends on |
|------|------------------------------------|------------|
| PR-A | P0-1, P0-2, P0-3                   | —          |
| PR-B | P1-1, P1-2 (`end_node` transaction)| PR-A       |
| PR-C | P1-3 (read/write boundary)         | —          |
| PR-D | P2-1..P2-5 (docs, templates, role, warnings, strategy_reflection) | PR-A |

PR-A and PR-D together close the immediate `n025/n026/n027` class of problem
without any schema change. PR-B and PR-C repay the deeper control-plane debt
so future docs work does not sit on shifting ground.
