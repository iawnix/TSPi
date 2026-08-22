# TSAgentSkill Architecture

This document defines component ownership and runtime boundaries for
`@iawnix/ts-agent` protocol v4. JSON and TypeBox schemas are authoritative for
field-level call shapes. The Root Skill is authoritative for behavior inside a
research session. [ADR 0001](adr/0001-dag-research-kernel-v4.md) records why
this is an incompatible DAG-based design.

## System Shape

```text
Installation root
  TSPi shell shim
    -> Python lifecycle host
       -> immutable selected release and isolated Python runtime
       -> workspace bootstrap and one-writer Root lock
       -> Pi process
          -> Root Skill + five extensions + theme
          -> Root Agent
             -> v4 Research Kernel
                Claim graph + ResearchAct DAG
                Observation and Finding registries
                Decision transaction owner
             -> deterministic execution plane
                compute kernel + Render + Report + remote + notification
             -> Validation Engine
                frozen GateSpecs + registered predicates + acceptance profiles
             -> graph Context Compiler
             -> isolated operational Compute Agent
             -> isolated advisory Review Agent
          -> read-only TS Activity and history projection
```

There are three forms of execution:

1. **Root Agent reasoning** selects scientific questions, hypotheses, methods,
   alternatives, counterexamples, backtracking, stopping, and interpretation.
2. **Bounded child-agent execution** has two roles. Review evaluates a compact
   Claim-centered snapshot and returns non-authoritative advice. Compute
   orchestrates one host-bound action plan and has no scientific discretion.
3. **Deterministic host execution** validates and commits state or performs an
   explicitly selected side effect. Every compute action, structure seed,
   Render, Report, remote inspection, artifact import, notification, context,
   and validation operation is implemented outside the child model.

## Authority Matrix

| Component | Uses a model | Writes canonical science | External effect | Durable output |
| --- | --- | --- | --- | --- |
| TSPi lifecycle host | No | Bootstrap only | Starts Pi | release/config selection, identity, Root lock |
| Root Agent | Yes | Only through Decision apply | Selects bounded tools | Pi conversation and applied Decisions |
| Research Kernel | No | Yes, exclusively | No | graph registries, acceptance, Decisions, transactions |
| Context Compiler | No | No | No | revision-bound read projection |
| Validation Engine | No | Through Kernel apply | No | frozen GateSpecs and ValidationResults |
| Review Agent | Yes | No | No | task, snapshot, result/failure, Root disposition |
| Compute Agent | Yes | No | Only through bound typed tools | task, actions, deterministic result/failure |
| Compute kernel | No | No | Local/SSH/Torque action | intent, control record, manifest, parsed artifacts |
| `ts_structure_seed` | No | No | Bounded local generation | Act-owned XYZ, provenance, and activity |
| `ts_artifact_import` | No | No | Bounded local file creation | Act-owned content-addressed input and activity |
| `ts_render` / `ts_report` | No | No | Local file creation | no-overwrite artifact or report package |
| `ts_remote_inspect` | No | No | Read-only SSH/Torque calls | tool result only |
| `ts_notify_user` | No | No | Fixed-target ClawEmail delivery | digest-addressed receipt |
| TSPi UI and `ts_web` | No | No | Read-only projection | transient UI or explicit UI registry |

Only `ts_workspace_decision_apply` may mutate canonical scientific state after
bootstrap. No extension, Review result, backend, parser, scheduler, renderer,
report builder, notification, UI event, or Agent prose may bypass that owner.

## Scientific State Model

### Claim graph

A Claim contains a scientific statement, open `claim_type`, assumptions,
falsifiers, tags, status, and exact Observation/validation history. A separate
ClaimRelation record connects two Claims with an open scientific relation label
such as dependency, refinement, conflict, or alternative. The Kernel enforces
acyclic directed relations but does not interpret a label as permission to act.
ClaimRelation IDs are readable workspace-local ordinals (`rel_1`, `rel_2`, ...).
Claim IDs are workspace-local monotonic ordinals (`claim_1`, `claim_2`, ...),
used only as immutable identity and never as confidence, priority, or policy.
`ResearchAct.claim_refs` records Claims in an Act's declared scope, while
`Claim.created_by_act` records the Act in which a new Claim originated. They are
not mirrored fields. Read projections derive the Claim-Act neighborhood from
their union so provenance-only links remain visible without canonical rewrites.

### ResearchAct DAG

A ResearchAct is one bounded and auditable act. It records:

- an objective and optional hypothesis package;
- zero or more dependency Acts;
- related Claims and descriptive tags;
- Observations, Findings, GateSpecs, and ValidationResults linked by canonical
  scientific refs;
- one terminal result or an open status;
- the Kernel-owned artifact root `acts/<act_id>`.

Dependencies form a DAG. One dependency creates an ordinary continuation;
multiple dependencies model a merge; a new Act that depends on an earlier Act
models backtracking. Prior Acts are never rewritten or deleted to make a later
path look linear. The DAG records lineage and does not select the next Act.

### Observation and Finding

An Observation is immutable and semantic. It binds a `concept_id`, subject,
typed value, unit, qualifiers, summary, logical artifact IDs, artifact digests,
producer, producing Act, and creating Decision. Parsers must emit declared
concepts directly; the Kernel does not guess aliases for arbitrary output keys.
Observation IDs are readable workspace-local ordinals (`obs_1`, `obs_2`, ...);
the record fields, not the ordinal, carry scientific meaning.

A Finding makes an anomaly, conflict, limitation, or unresolved question
queryable. It may cite Claims, Acts, and Observations. Findings can be blocking,
warning, or informational. A Finding remains open until an explicit Decision
resolves, accepts, or supersedes it. Open blocking Findings prevent acceptance
of affected Claims.
Finding IDs are readable workspace-local ordinals (`fnd_1`, `fnd_2`, ...).

### Validation and acceptance

A GateSpec is a fully expanded, frozen declarative check set. It records the
target Claim, dimension, template digest when applicable, predicate-registry
digest, checks, success policy, creator Act, and content digest. A
ValidationResult records selected Observation refs and digests, each predicate
outcome, the aggregate verdict, and a result digest.
GateSpec and ValidationResult IDs are likewise readable creation ordinals
(`gsp_1`, `gsp_2`, ... and `val_1`, `val_2`, ...).

The four verdicts are distinct:

```text
pass | fail | inconclusive | error
```

`inconclusive` means available valid inputs cannot decide the specification.
`error` means the specification could not be executed as declared. Neither is
a passing result.

Claim status is an explicit Root interpretation; acceptance is a separate
immutable assessment snapshot. A versioned acceptance profile checks a
supported Claim, at least one GateSpec, required dimensions, coverage of all
attached GateSpecs, the latest passing result per specification, content
digests, and blocking Findings. Historical records remain canonical. Their
currentness is derived by comparing the frozen Claim, profile, GateSpecs,
latest results, and relevant Findings with current canonical state. The entire
acceptance record is also self-bound by `acceptance_digest`.
Acceptance IDs and filenames use readable ordinals (`acc_1`, `acc_2`, ...).

### Open scientific vocabulary

Claim types, relation types, Act tags, Finding types, validation dimensions,
Observation concepts, and subjects remain open strings because they express
research meaning. Closed enums exist only where deterministic code must execute
a closed contract, such as record status, value datatype, finding severity,
validation verdict, and Decision operation.

There is no workflow phase, stage, Act type, scientific role/layer, backend
priority, or fixed Gate-to-action router.

## Canonical And Operational State

Canonical v4 state is:

```text
workspace.json
research_state.json
claims.json
claim_relations.json
research_acts.json
observations.json
validation_specs.json
validation_results.json
findings.json
acceptances/<acceptance_id>.json
decisions/<decision_id>.json
decision_log.jsonl
transaction_log.jsonl
```

These records determine `workspace_revision`. Direct edits are unsupported.

Operational or derived state includes:

```text
acts/<act_id>/attempts/...
acts/<act_id>/outputs/...
operations/agent-runs/...
acts/<act_id>/activities/...
operations/activities/...
reports/...
.pi/ session and lock state
remote guards, receipts, and mirrored files
notification receipts
```

Operational state may determine `operational_revision`, but it does not change
a Claim, Observation, Finding, ValidationResult, or acceptance record.

## Decision Transaction

The only normal mutation sequence is:

```text
context -> decision draft -> complete dry-run validation -> apply under lock
```

`ts_workspace_decision_draft` accepts Root-authored v4 operations and local
aliases. It allocates technical IDs, resolves `$alias` references, compiles any
GateSpec, evaluates any requested validation against the draft state, binds the
current frontier projection and scientific revision, and returns a complete
`ts-research-decision/1`.

Validation applies the exact Decision to an isolated copy of canonical state
and validates the complete post-state. Apply repeats binding and post-state
validation while holding the workspace lock, then commits through one
transaction path. A Decision is idempotent only when its ID and full canonical
digest match. Decision IDs are workspace-local monotonic ordinals (`dec_1`,
`dec_2`, ...), used only as immutable identity. Drafting does not reserve an
ordinal: parallel drafts may receive the same next ID, the first committed
content owns it, and a conflicting draft must be redrafted. Committed, aborted,
and recoverable transaction IDs are never reused. Any edit after draft requires
a new draft.

Supported draft operations are:

```text
create_claim            relate_claims
start_act               complete_act
record_observation      record_finding      resolve_finding
freeze_validation_spec evaluate_validation
update_claim            accept_claim
set_focus
```

These are state primitives, not a prescribed sequence. A single Decision may
contain multiple ordered operations and refer to new records with local aliases.

## Validation Engine

The engine separates mechanism from policy:

```text
Gate template + typed parameters
  -> compiler expands every check
  -> frozen GateSpec with template and registry digests
  -> registry invokes maintained deterministic predicates
  -> ValidationResult with selected Observation digests

Acceptance profile
  -> required dimensions + coverage rules + blocker rules
  -> immutable assessment snapshot + derived currentness
```

The Root Agent may select a packaged template or provide a declarative
definition composed only of registered predicates. A definition cannot contain
Python, shell, imports, expressions, or executable plugins. New deterministic
scientific behavior enters through maintained predicate code, tests, and a new
registry digest.

Built-in classical TS templates are ordinary packaged templates. Photochemical,
metal-catalyzed, radical, crossing, or dynamics work can add new templates and
predicates without adding a new workflow branch.

## Context Compiler

The model receives revision-bound graph projections rather than raw canonical
files. Graph modes are:

- `frontier`: focus Claims/Acts, direct alternatives/dependencies, open
  Findings, incomplete validation, and recent object-level changes;
- `claim`, `act`, `finding`, and `validation`: one focused object and bounded
  neighborhood;
- `subgraph`: caller-seeded Claim/Act graph to a bounded depth;
- `delta`: changes since known scientific and operational revisions.

The same read-only public tool exposes `artifacts`, `compute_capabilities`, and
`validation_capabilities`. Every bounded graph projection reports omitted
counts and retrieval hints. The Pi transcript is conversational state, not a
scientific source of truth.

Claim-Act traversal uses the union of declared Act scope and Claim creator
provenance. Context, Review, report rendering, and `ts_web` share this derived
relationship; none mutates the underlying Claim or ResearchAct records.

Validation capability discovery is progressive: the catalog is compact, while
an exact `templateId` plus `templateVersion` returns that template's accepted
parameters and expanded Observation selectors before a GateSpec is drafted.

## TSPi Lifecycle

`TSPi` is a thin shell shim. `scripts/tspi_host.py` and
`ts_runtime/launcher.py` own lifecycle behavior:

1. Resolve the physical installation root and immutable selected release.
2. Resolve installation-owned runtime, remote, notification, and cache paths.
3. Select the isolated Python interpreter before importing workflow code.
4. Validate the workspace name and create or reuse
   `<installation>/workspaces/<name>`.
5. Create workspace-local Pi session settings and acquire a nonblocking Root
   Agent lock.
6. Initialize fresh v4 state once or validate a complete v4 workspace without
   rewriting it. Partial, invalid, or legacy canonical state fails closed.
7. Execute Pi with exactly the package Skill, theme, and five extensions.

One workspace has one Root writer process. Different workspaces can run
concurrently while sharing immutable code and the Python environment. They do
not share Pi conversations, graph state, calculations, reports, or locks.

A Pi conversation may contain many user/assistant turns. ResearchAct completion
changes the workspace, not the transcript. A later turn learns the change from
the tool result already in context or a new context projection. Terminal mode
resumes only when `--continue` is supplied; Phone mode supplies it automatically.

Before each Root run, the control extension appends a short package-source and
active-workspace reminder to Pi's native system prompt. It does not inject a
full workspace dump.

## Public Extensions

| Extension | Public tools and commands | Responsibility |
| --- | --- | --- |
| `ts-workflow-control` | context, Decision draft/validate/apply; `/ts-context`, `/ts-validate` | graph projection and sole canonical mutation path |
| `ts-workflow-review` | `ts_subagent_review`, `ts_review_disposition` | isolated advisory Review and mandatory Root response |
| `ts-workflow-compute` | `ts_subagent_compute`, `ts_remote_inspect`; `/ts-remote` | isolated operational lifecycle over deterministic compute actions and diagnostics |
| `ts-workflow-artifacts` | `ts_structure_seed`, `ts_artifact_import`, `ts_render`, `ts_report`, `ts_notify_user` | deterministic local artifacts, reports, and delivery |
| `ts-workflow-ui` | `/ts-subagent-history` | startup, editor/footer, TS Activity, and Compute/Review history |

`ts-phone-bridge` is optional and loaded only by `TSPi --phone`. It forwards
messages to the same visible Pi process and never creates a hidden Root Agent.

The shared tool catalog is an inventory and execution classification, not a
complete capability contract. Registered tool schemas define call fields;
compute capabilities define expressible adapter tasks; validation capabilities
list templates, predicates, and profiles; remote diagnostics establish live
readiness.

## Isolated Agent Runtimes

Compute and Review share the same process-level safeguards: a fresh in-memory
Pi session, inherited model identity without fallback, no parent transcript,
no Skills or package extensions, no built-in tools, no recursive delegation,
bounded task/result contracts, local validation, one structural repair, and
provider-error-first reporting. Their authority and available tools differ.

### Review

Review exists because its value depends on independent scientific reasoning.
The host:

1. selects one target Claim and asks the Context Compiler for its dependency
   snapshot;
2. creates a bounded `ts-agent-task/2` containing compact Claim, relation, Act,
   Observation, Finding, GateSpec, ValidationResult, and a logical artifact
   manifest without paths or file contents;
3. starts a fresh Pi child session with no parent transcript, Skills,
   extensions, direct filesystem, shell, compute, mutation, or delegation;
4. enables `ts_review_result` plus, only when artifacts were selected, one
   batch-only `ts_review_artifact_read` tool; the initial turn may read once or
   submit directly, and every post-read or repair turn forces the result tool;
5. verifies path containment, size, SHA-256, Claim ownership, section and byte
   budgets before returning any excerpt, while journaling metadata but no text;
6. validates `ts-agent-result/1` locally against task identity, scope, citation
   allowlist, and advisory authority;
7. permits at most one same-session structural repair;
8. records provider failures before classifying missing or invalid output.

Provider-side strict function mode is not required. Local TypeBox and semantic
validation remain authoritative. Review cannot mutate state, create scientific
Observations, perform external effects, or accept a Claim.

Every successful Review requires exactly one deterministic
`ts_review_disposition` before the next scientific mutation. Accepting advice
still requires primary artifacts and a normal Decision.

### Compute

`ts_subagent_compute` receives one `ts-agent-task/2` with
`role=compute`, `authority=operational`, one Act, one immutable intent digest,
and one of four closed plans:

```text
launch   prepare -> submit
inspect  status -> optional tail
finalize collect -> parse
cancel   cancel
```

Before the child starts, the host creates or resolves the intent and completes
all path, identity, digest, backend, and execution-target checks. Each child
action is a zero-argument tool bound to that preflight result. A prerequisite
must complete before a dependent action; every action can be called at most
once. `submit` and `cancel` are never replayed after an unknown effect. After a
terminal plan, the host forces `ts_compute_result`. The model supplies only
`summary` and `limitations`; the host derives all outcomes, facts, program
state, artifacts, provenance, and reconciliation flags from typed action
receipts.

## Deterministic Tool Plane

### Compute

The private compute kernel performs `prepare`, `submit`, `status`, `tail`,
`collect`, `cancel`, or `parse`. Preparation binds one ResearchAct, logical input artifacts and roles,
backend/task/settings, execution target, and expected outputs into an immutable
`ts-calculation-intent/4`. The host allocates paths, filenames, intent ID,
remote directory, and submission binding.

Remote transport uses OpenSSH/SCP and Torque directly. Guards distinguish
pre-effect retryable failure from an ambiguous external effect. Known job IDs
are retained even if later scheduler inspection fails. Collection follows the
immutable manifest and does not require queue history.

### Structure Seed And Artifact Import

`ts_structure_seed` accepts one connected SMILES plus declared charge,
multiplicity, and `none` or `uff` initialization. The host uses fixed-seed
RDKit ETKDGv3, explicit hydrogens, charge/electron-parity checks, and optional
UFF optimization. It writes private, content-addressed XYZ and provenance files
under one open ResearchAct. The request journal stores the submitted digest,
not the SMILES body. The resulting geometry and any UFF energy are initialization
diagnostics, never stationary-point, TS, or acceptance evidence.

`ts_artifact_import` closes the empty-workspace bootstrap boundary. It accepts
bounded inline Gaussian, XYZ, or xTB control text for one open ResearchAct,
checks structure metadata and format, and writes a private content-addressed
file under the Act. Callers cannot provide a path or filename. Repeating
identical content is idempotent; conflicting or unsafe targets fail closed.
Only digest, size, format, chemical metadata, and the resulting logical
artifact are journaled, never the input body.

### Render and Report

`ts_render` validates one Act-owned input set and creates one no-overwrite local
artifact. `ts_report` validates the workspace, creates a new report directory
atomically, and verifies the package manifest and file digests. Neither uses a
model or interprets chemistry.

### Notifications

`ts_notify_user` sends a fixed event shape to the installation-owned recipient
through configured ClawEmail. Recipient and credentials are not model fields.
Digest-bound receipts make known success idempotent; ambiguous provider effects
are not replayed automatically.

## Run Journals And Result Delivery

Compute and Review journals live under:

```text
acts/<act_id>/agent-runs/<task_id>/
```

At creation, `task.json` and its bound snapshot are exclusive-created. Normal
terminal handling writes actions, optional result, and final run state. A
process crash can leave a task-only journal indexed as pending/unknown; there is
no claim of per-event write-ahead durability or automatic result replay.
If terminal journal persistence itself fails, the runtime preserves the primary
provider or action error, reports the journal failure separately, and leaves the
run pending rather than rewriting the remote action outcome.

Deterministic operations use the Activity Journal as their single activity
source of truth. Every request/status record carries `act_refs`; a shared
Activity Index validates IDs, paths, ownership, status/result consistency, and
referenced Acts, then derives per-Act activity projections. ResearchAct records
do not duplicate activity refs and no Decision is needed to link an operation.
Compute guards and receipts remain the source for scheduler recovery; a UI or
agent-run state never proves a remote effect.

An Act cannot become terminal while one of its activities is running or
pending, its activity journal is inconsistent, or a compute control is pending
or unresolved. A failed terminal activity may close only as `inconclusive`,
`blocked`, or `stopped`. An analytical Act with no activity remains valid.

The immediate tool return is the current delivery channel into the Root
conversation. `TS Activity` is presentation state and is cleared with the Pi
session. `/ts-subagent-history` reads durable Compute and Review summaries on demand.

## Failure Semantics

- A schema, binding, or staging failure before an external effect is not an
  ambiguous submission.
- A missing scheduler reply after effect initiation is unknown until durable
  records or declared outputs reconcile it.
- Program failure is not automatically scientific contradiction.
- Parser failure is not automatically program failure.
- A successful deterministic action is not undone by a later UI or report-entry
  serialization error.
- Provider HTTP/stream failure outranks Compute/Review output-contract failure.
- Canonical corruption, stale revision, digest drift, cyclic graph, and partial
  bootstrap fail closed.

## Contract Locations

| Contract | Owner |
| --- | --- |
| Public tool names and execution classes | `extensions/shared/tool-catalog.ts` |
| Public call schemas | each `extensions/ts-workflow-*/index.ts` |
| Agent task/result envelopes | `contracts/agent_task.schema.json`, `contracts/agent_result.schema.json` |
| Canonical scientific records | `ts_workspace/contracts/*.schema.json` |
| Decision normalization and ID allocation | `ts_workspace/decision.py` |
| Transactional mutation and validation | `ts_workspace/engine.py`, `ts_workspace/validator.py` |
| Graph projections and Review snapshot | `ts_workspace/context.py` |
| Predicate registry and GateSpec compiler | `ts_validation/` |
| Built-in validation policy | `ts_validation/templates/`, `ts_validation/acceptance_profiles/` |
| Compute request, intent, and result | `ts_compute/contracts/*.schema.json` |
| Backend capabilities and parsers | `ts_compute/capabilities.py`, `ts_backends/` |
| Remote lifecycle | `ts_remote/` |
| Artifact import/catalog contract | `ts_compute/artifacts.py`, `ts_compute/cli.py` |
| Render/report request/path contract | `src/artifacts/request-contract.cjs` |
| Report projection | `ts_report/` |
| Package/release boundary | `package.json`, `scripts/check_package.py`, installer tests |
