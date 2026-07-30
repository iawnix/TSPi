---
name: transition-state-workflow
description: Plan, run, validate, and reflect on transition-state searches with a chemistry-hypothesis-driven workspace, decision JSON mutations, explicit mechanism branches, structure analysis, backend adapters, remote execution helpers, read-only web visualization, and final report assembly.
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
- `ts_structures`: structure analysis only. It parses XYZ structures,
  computes geometry/RMSD/stereochemical metrics, and returns evidence-shaped
  results; it never writes a workspace.
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
- `ts_web`: rendering-only explorer. It reads workspace state and prepares
  it for the browser UI; it does not mutate the source workspace. UI state
  (workspace registry, user preferences) lives in an explicit `--state-dir`
  that must not be inside the source workspace. Every label, color, and
  `claim_state` in the payload comes from `ts_web`'s read layer; the browser
  frontend keeps no vocabulary of its own and does no state derivation. When
  the same derivation is needed outside the web UI, promote it to
  `ts_workspace/readers/` and have `ts_web` consume it from there — do not
  duplicate. Start with
  `python "$TS_AGENT_SKILL_ROOT/scripts/ts_web.py" serve --state-dir <state> --port 8766`.
  Pass `--source-root <root>` (repeat for multiple workspaces) and matching
  `--label <name>` to register on startup. Default bind is `0.0.0.0` for
  LAN-visible TS monitoring. Manage the registry with
  `python "$TS_AGENT_SKILL_ROOT/scripts/ts_web.py" register|list|remove --state-dir <state> ...`.
- `ts_report`: final report package assembly from validated workspace
  evidence. It can emit Markdown, a report context JSON, visual assets, and an
  email summary; missing render or energy data must be reported explicitly.

## Authority Model

The workspace enforces evidence integrity, atomicity, and provenance; it does
not decide research direction. Route selection, retry vs. reformulate, and
hypothesis switching are agent decisions guided by references and templates,
not by validators. A rule is code only if violating it corrupts state that
later reads cannot recover from; otherwise it is a template default, a
validator warning, or a reference heuristic. Generic patterns live in this
skill; project-specific priors live in the project's own `.TODO.md` or
README, not in shared references.

Concretely:

- Hard errors: schema shape, evidence-gate structure, references existing,
  provenance present, cross-file topology (e.g. `parent_node ==
  branch_context.anchor_node` for anchored relations).
- Soft warnings: patterns that are usually wrong but sometimes legitimate
  (e.g. `new_solution_branch` after only an IRC-parameter change).
- Templates: default decision shapes named by scenario so the right choice
  is the easy choice.
- References: symptom-triggered reflection (mechanism identity, route
  strategy) that guides the next decision without gating it.

## Pi Scientific Review Subagent

Pi exposes `ts_workspace_subagent` for one bounded, independent review at a
high-value decision boundary: unresolved mechanism ambiguity, candidate or
TS/Freq quality concerns, connectivity conflicts, program-failure diagnosis,
backtrack selection, or final-audit readiness. Do not call it every turn or
after every tool result. Select a node or backtrack pair and only the evidence
and text artifacts needed for the question.

Each call uses a fresh in-memory, tool-free child session. It receives no parent
history, skills, extensions, context files, or workspace write authority. Its
structured result is advisory analysis, not registered evidence, a branch
decision, an accepted-TS verdict, or pathway acceptance. The root agent must
compare cited findings with primary artifacts, identify conflicts and missing
evidence, then make and validate its own decision. Never copy a subagent claim
into workspace state as evidence unless a deterministic artifact or registered
evidence record independently supports it.

## Public Control Plane

Two disjoint command sets. Mutation commands change workspace state and
require a decision JSON. Read/support commands do not.

All shell examples assume an explicit skill root:

```bash
export TS_AGENT_SKILL_ROOT=/path/to/transition-state-workflow
```

**Mutation CLI:**

```bash
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" init_workspace  --root <root> [--decision-file decision.json] [--force]
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" start_node      --root <root> --decision-file decision.json
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" propose_hypothesis --root <root> --decision-file decision.json
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" update_workspace --root <root> --decision-file decision.json
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" end_node        --root <root> --decision-file decision.json
```

**Read / Support CLI:**

```bash
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" report_workspace   --root <root>
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" snapshot_report    --root <root>
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" validate_workspace --root <root>
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" validate_decision  --root <root> --decision-file decision.json
```

`report_workspace` returns the current context but does not write; use
`snapshot_report` to also persist `reports/<report_id>.json`. `init_workspace`
refuses to overwrite an initialized workspace unless `--force` is passed;
`--force` is destructive and removes workspace-owned state before recreating the
workspace, so it requires an `init_workspace` decision JSON.

Every applied mutation records a full decision snapshot at
`decisions/<decision_id>.json` and a `snapshot_ref` in `decision_log.jsonl`,
so audits and future replays do not depend on the log row alone. Reusing a
`decision_id` is allowed only when the stored snapshot content is identical and
already committed; it becomes a no-op. Different content with the same
`decision_id` is rejected before mutation.
Mutations are transactional: a `transaction_log.jsonl` `prepare` row is written
with the exact paths, the decision snapshot is written before state files, all
writes are applied, then a `committed` row closes the transaction.
`validate_workspace` reports
`pending_transaction` (warning) if a `prepare` is not followed by
`committed`, so crash-interrupted closes are detectable.

Except for first-time bootstrap, mutation commands must be traceable to a
decision JSON. The mutation command validates the decision internally; a
separate `validate_decision` call is only a preflight. Public preflight is
workspace-aware: it validates both the JSON shape and contextual requirements
such as required post-`n000` `payload.branch_context` provenance.

Gaussian local helper entrypoints are thin wrappers around backend boundaries:

```bash
python "$TS_AGENT_SKILL_ROOT/scripts/ts_backend.py" gaussian prepare --help
python "$TS_AGENT_SKILL_ROOT/scripts/ts_backend.py" gaussian parse --help
```

Runtime and visualization entrypoints:

```bash
python "$TS_AGENT_SKILL_ROOT/scripts/install_env.py" --package-root "$TS_AGENT_SKILL_ROOT" --workspace-root <workspace> --json
python "$TS_AGENT_SKILL_ROOT/scripts/ts_render.py" diagnostic --json
python "$TS_AGENT_SKILL_ROOT/scripts/ts_render.py" render input.xyz -o nodes/n001/outputs/render.png
python "$TS_AGENT_SKILL_ROOT/scripts/ts_render.py" compare reactant.xyz ts.xyz product.xyz -o nodes/n001/outputs/compare.png
python "$TS_AGENT_SKILL_ROOT/scripts/ts_render.py" animate irc.xyz -o nodes/n001/outputs/irc.mp4
python "$TS_AGENT_SKILL_ROOT/scripts/ts_report.py" --root <root> --package-dir reports/final_report_package
```

After installation, public scripts and the Pi extension prefer the interpreter
recorded in the resolved runtime manifest. With a workspace root, the default
manifest is `<workspace>/.agents/runtime/transition-state-workflow/env.json`
and the Conda prefixes live under
`<workspace>/.agents/envs/transition-state-workflow/`. Legacy
`package-root/.runtime/env.json` manifests are read only when no explicit
workspace root, runtime home, or manifest path is supplied.

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

- `endpoint`
- `candidate_generation`
- `tsfreq_validation`
- `connectivity_validation`
- `accepted_audit`
- `pathway_audit`

Legacy `preflight`, `rp_conformer_generation`, and `hypothesis_generation`
nodes remain readable and closable. New `start_node` decisions cannot create
them.

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
   `endpoint` node before candidate generation. Use it only for
   source hashes, charge/multiplicity, atom mapping, endpoint sanity checks,
   and endpoint evidence. Close it before proposing the initial mechanism
   hypothesis; do not put mechanism-hypothesis creation, TS/Freq, IRC,
   connectivity, or accepted-TS claims in `n000`.
   Reactant/product endpoints define target basins for validation, not the
   candidate-generation method. Do not default to QST2/QST3 merely because R/P endpoints
   are available; justify QST use from endpoint optimization, atom mapping,
   conformer compatibility, and the elementary-step model.
3. Run `report_workspace` before deciding the next node. Read
   `references/agent_decision_protocol.md` before closing a node, choosing a
   branch relation, or deciding whether a previous failed exploration should
   affect the next action.
   The canonical root state consists of `research_state.json`,
   `hypotheses.json`, and `evidence_registry.json`; reports and knowledge
   summaries are derived views. Use `report_node --node-id <node>` when an old
   checkpoint may be relevant. Before a graph rebase, use
   `report_branch_context --from-node <trigger> --anchor-node <checkpoint>` to
   load the trigger, selected checkpoint, and attempts between them.
4. Construct a decision JSON with the action, rationale, report reference,
   evidence references, and payload. Start from `templates/decision/` when a
   reusable shape is needed; do not copy JSON from `tests/`. Every post-`n000`
   evidence-testing node must include `payload.hypothesis_ref` that points to
   `hypotheses.json.hypotheses[]`. Use optional `payload.solution_ref` only to
   group alternative search strategies under the same hypothesis; it is
   lineage metadata, not a new state, verdict, or retry policy. Every post-`n000`
   `start_node` must include `payload.branch_context` so the agent's intended
   graph relation is explicit.
   Introduce the initial or a later mechanism hypothesis with the
   `propose_hypothesis` mutation. It writes `hypotheses.json` but creates no
   node. A proposal must cite registered evidence and records `source_node`,
   `branch_anchor_node`, and `proposal_context`. The first evidence-producing
   node activates the proposed hypothesis. For an alternative proposal, that
   node must use `branch_context.relation=new_hypothesis_branch` and exactly
   match the stored proposal provenance.
   For `phase=pathway_audit`, `start_node.payload.pathway_ref` is mandatory
   and must identify the audited `pathway_id` and `step_id`; this is the only
   phase where `pathway_ref` is required by the start-decision contract.

   **Branch relation decision table** — pick one:

   | Situation | `relation` | Notes |
   |---|---|---|
   | Same scientific object continues to next evidence layer (candidate → TS/Freq, TS/Freq → IRC, IRC → accepted audit, accepted → pathway audit) | `continue_parent` | `parent_node == from_node`. |
   | Same TS claim, IRC/protocol parameters changed after a program failure | `continue_parent` | `parent_node = TS/Freq-supported node`, `from_node = same`; cite the failed attempt via `reason_code` + evidence with role `previous_attempt_summary`. |
   | Same hypothesis, different candidate / search strategy | `new_solution_branch` | New `solution_ref.solution_id`; agent selects an ancestor checkpoint and sets `parent_node == anchor_node`. |
   | First evidence node for an alternative proposed hypothesis | `new_hypothesis_branch` | Match the stored `proposal_context`; `parent_node == anchor_node`, and the anchor must be an ancestor of `from_node`. |
   | Different pathway topology / step model | `new_pathway_branch` | `parent_node == anchor_node`; anchor must be an ancestor of `from_node`. |

   **Program failure follow-up is not automatically a new branch.** A
   scheduler failure, IRC corrector convergence failure, parser desync, or
   Gaussian route ineffectiveness that continues verifying the same
   scientific claim is `continue_parent`, not `new_solution_branch`. Reserve
   `new_solution_branch` for real candidate/search-strategy replacement.

   `ts_workspace` records and validates topology; it must not decide whether
   to retry, switch solution, switch hypothesis, or stop.
5. Run `validate_decision` for preflight when useful.
   In Pi, use the read-only `ts_workspace_decision_validate` tool; the separate
   `ts_workspace_decision` tool accepts mutation actions only.
   Monitoring, report packaging, snapshots, workspace visualization, and other
   control-plane support do not create nodes. Use their read/support commands or
   `update_workspace` when an explicit supported mutation exists.
6. Apply the mutation through `start_node`, `propose_hypothesis`,
   `update_workspace`, or `end_node`.
7. Use `ts_backends`, `ts_remote`, and `ts_structures` to create artifacts and
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
   questions. Before closing a `pathway_audit` node, register a
   `pathway_audit_summary` evidence record whose
   `quality.strict_pathway_decision` is `accepted` or
   `pathway_not_accepted`, then cite that evidence in the `end_node` decision.
   `claim_verdict=supported` on the
   audit node supports the audit conclusion only; it is not by itself pathway
   success.
9. Use `update_workspace` with `payload.repair_branch_anchor` only for explicit
   lineage repair of non-running `new_solution_branch` nodes. The replacement
   anchor must be an ancestor of the recorded `from_node`; the repair records
   an audit entry and does not alter the historical checkpoint.
10. Run `report_workspace` again before branching or stopping.
11. Use `ts_report` only after the workspace validates. Prefer report-package
   output for final handoff so structure panels, vibration/IRC plots, energy
   profile, mechanism interpretation, context JSON, and email summary are kept
   together. Energy profiles must distinguish electronic, E+ZPE, and available
   free-energy relative values; missing R/P/TS corrections must be reported as
   missing rather than silently replaced by electronic energies.

## References

Read only the reference needed for the current task:

- `references/workspace_contract.md`
- `references/agent_decision_protocol.md`
- `references/decision_contract.md`
- `references/state_model.md`
- `references/pathway_model.md`
- `references/ts_structures_contract.md`
- `references/runtime_environment.md`
- `references/render_contract.md`
- `references/report_template.md`
- `references/backend_contract.md`
- `references/remote_contract.md`
- `references/program_runtime_failures.md`
- `references/mechanism_reflection.md`
- `references/backend_selection.md`
- `references/candidate_generation.md`
- `references/gaussian_validation.md`
- `references/connectivity_validation.md`
- `references/strategy_reflection.md`

Read `references/strategy_reflection.md` when any of the following holds:
(a) the same `hypothesis_ref` has ≥2 consecutive nodes whose IRC endpoint
assignments fall on the same side (product/product or reactant/reactant);
(b) the same `hypothesis_ref` has ≥2 Gaussian route-mismatch diagnostics
or route-ineffective closures;
(c) the active hypothesis `structured_claim.electronic_model`
marks `excited_state`, `open_shell`, or `non_adiabatic`;
(d) any recent `reason_code` matches `wrong_basin|route_ineffective|surface_ambiguous`.

Read `references/program_runtime_failures.md` whenever a calculation, remote
submission, parser, optimizer, SCF, IRC, scratch, or artifact-fetch issue
prevents the node from producing usable evidence. It guides troubleshooting and
decision framing only; it does not add fields or choose retry/branch policy.

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
