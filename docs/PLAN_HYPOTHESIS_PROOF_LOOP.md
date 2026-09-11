# TSPi Hypothesis--Proof Loop Refactor Plan

- Status: implementation complete in the authored checkout; commit, publication,
  and production installation remain explicit delivery steps
- Working branch: `ts-hypothesis-loop`
- Scope: TSPi Agent, deterministic research kernel, embedded Web explorer,
  TS Phone component, and the unified release package

The plan is a living implementation record. The current checkout has already
landed the kernel, capability, candidate, ProofSpec, bounded-context, isolated
agent, Web projection, and package-boundary changes described below. The
remaining work is to make every public document and schema describe the same
contract, make unsupported execution modes fail with an explicit error, and
complete source/package/runtime verification before release.

### Implementation snapshot

Completed in this branch:

- Phase/Node/Claim graph and the single `ts_change` mutation boundary;
- capability-driven calculation requests with immutable Attempt lineage;
- parser `ObservationCandidate` output and explicit Root promotion;
- versioned, digest-bound `ProofSpec` compilation and deterministic evaluation;
- bounded frontier/delta context and logical artifact resolution;
- isolated Compute and advisory Review runtimes with provider-error-first
  reporting;
- Node-first Web projection, Attempt/Run detail views, and the unified TSPi
  package source boundary;
- Python kernel wheel packaging and release/package checks.

Validation already performed from the authored checkout includes the complete
Python suite (`546 passed` in the latest managed source run), TypeScript
typecheck, package completeness check, Python bytecode compilation, and
`git diff --check`. These checks validate the current source snapshot; they do
not publish or install a release.

The authored redesign is now internally consistent. The remaining delivery
step is to run the clean component/package build and runtime/Phone integration
validation described in Milestone G after an explicit commit/push authorization;
those actions are intentionally not implied by source-level tests.

## 1. Decision To Make

TSPi must support research questions that were not known when the package was
written. A central router of the following form is therefore out of scope:

```text
hypothesis -> if/else table -> predetermined calculation sequence
```

Adding a new scientific domain to that design requires enumerating more cases,
and eventually makes the acceptance checklist more important than the
question. The replacement is a capability-driven hypothesis--proof loop:

```text
Root Agent formulates a question and hypothesis
        |
        v
Root Agent proposes a typed capability request
        |
        v
Kernel checks references, types, authority, state, and effects
        |
        v
Deterministic executor runs and records artifacts
        |
        v
Parser produces candidate observations
        |
        v
Root Agent interprets, records evidence, and chooses the next question
        |
        `--> continue, branch, backtrack, or stop
```

The kernel validates a proposed action. It does not infer the next action from
the Claim, Phase, Node tag, validation result, or domain vocabulary.

In this plan, "proof" means a versioned, falsifiable evidence test against a
declared standard. It does not mean mathematical proof or permanent certainty
about a chemical mechanism.

## 2. Product Boundary

The complete product is **TSPi**. It has one release identity and three
runtime-facing components:

```text
TSPi Package
├── Agent + Research Kernel       authoritative reasoning host and state
├── TS Web                        read-only research projection
└── TS Phone                      authenticated remote client and bridge
```

This is one distribution unit, not one process and not necessarily one source
repository. `ts-phone` may remain independently maintained so its mobile and
server toolchains stay manageable. TSPi's package builder must bind an exact
Phone component manifest, exact Agent release, protocol versions, and signed
APK into one content-addressed suite release. Only that suite release owns the
`current` selector used by production launchers.

Users install, upgrade, roll back, and report one TSPi semantic version. Agent,
Web assets, Phone server, mobile build, and wire-protocol versions remain
manifest-bound component details shown only in advanced diagnostics. A suite
cannot be assembled when those details are incompatible.

Source ownership and release ownership are intentionally different:

| Concern | Source owner | Runtime authority |
| --- | --- | --- |
| Scientific state, Agent, kernel | TSPi repository | TSPi Agent process |
| Research projection and static Web assets | TSPi repository | TS Web process, read-only |
| Phone server and mobile client | `ts-phone` repository | Phone bridge/server plus mobile client |
| Version binding and installation | TSPi package builder | TSPi installer |

Neither Web nor Phone becomes a second workspace store. Phone commands go
through the authenticated TSPi host, and Web reads validated projections.

## 3. Three Layers

### 3.1 Scientific Agent layer

The Root Agent owns the scientific work:

- questions, hypotheses, competing explanations, and assumptions;
- predictions and falsifiers;
- method and capability selection;
- interpretation of observations;
- deciding whether to continue, branch, backtrack, merge, or stop;
- deciding whether a proposed validation dimension is scientifically useful.

The Agent may use open scientific vocabulary. A new photochemical, metal,
radical, non-adiabatic, or otherwise unfamiliar hypothesis must not require a
new switch statement in the kernel.

The Agent does not allocate IDs, choose physical paths, claim that a program
ran successfully, or directly edit canonical state.

### 3.2 Research Kernel layer

The deterministic kernel is a type checker, transaction manager, provenance
ledger, and effect guard. It owns:

- canonical identities and references;
- workspace, Phase, Node, Claim, Observation, Finding, and validation schemas;
- transaction atomicity, locks, revisions, replay, and recovery;
- artifact ownership, digest checks, and logical path resolution;
- capability input/output compatibility and parameter limits;
- external-effect classification and ambiguous-result handling;
- deterministic predicates after a proof specification is frozen;
- error taxonomy and durable operational journals.

It must not own scientific strategy selection. In particular, graph relations,
ProofSpec verdicts, tags, and failed calculations may be reported to the Agent
but must not automatically select a successor action.

### 3.3 Capability and tool layer

Backends and services are finite implementations exposed through descriptors:

- Gaussian, xTB, CREST, NEB, excited-state or spin tools;
- structure import, seed generation, comparison, and rendering;
- local or SSH execution and scheduler control;
- report and notification delivery.

Each capability declares what it can express. Adding a capability means adding
an implementation, parser adapter, tests, and a versioned descriptor. It does
not mean adding a reaction-specific workflow branch.

The finite nature of executors is unavoidable. The extensibility boundary is
therefore the capability/plugin registry, not an ever-growing hypothesis
router.

### 3.4 Fixed envelope and open payload

The protocol coordinates deterministic code and Agent output by separating a
small fixed envelope from an open scientific payload:

| Fixed envelope, checked by code | Open payload, authored by Root |
| --- | --- |
| record kind and schema version | question and hypothesis text |
| IDs, refs, ownership, and revision | Claim type and relation meaning |
| typed scalar/list/object representation | scientific concepts and subjects |
| artifact role, path policy, and digest | assumptions, predictions, and falsifiers |
| action capability and parameter schema | rationale for selecting a capability |
| effect authority and retry semantics | interpretation and uncertainty |
| transaction and provenance metadata | branch, backtrack, and stop reasoning |

The kernel may reject a malformed value, stale reference, unsupported
capability, or unsafe effect. It must not reject a scientifically unfamiliar
Claim merely because its vocabulary has not appeared before. Conversely, open
text cannot name an executable program or predicate unless a registered
capability implements it.

## 4. Research Algebra

The protocol should expose a small set of composable records. Their scientific
strings remain open; only execution and storage invariants are closed.

| Record | Meaning | Authority |
| --- | --- | --- |
| `Claim` | A statement or hypothesis being investigated | Root-authored, kernel-validated |
| `ResearchPhase` | Human roadmap grouping | Navigation only |
| `ResearchNode` | One bounded decision episode and its principal deliverable | Root proposes, kernel owns identity |
| `CapabilityRequest` | One short-lived requested invocation and rationale | Root proposes, kernel preflights and journals |
| `CalculationIntent` / `Attempt` | One immutable compute intent and its concrete retries | Tool plane / operational journal |
| `Artifact` | Immutable file or logical output with digest | Kernel/artifact catalog |
| `ObservationCandidate` | Parser-produced, not-yet-accepted semantic value | Deterministic parser |
| `Observation` | Immutable cited semantic value | Kernel after explicit decision |
| `Finding` | Anomaly, conflict, limitation, or unresolved question | Root records, kernel validates |
| `ProofSpec` | Frozen declarative checks for one claim dimension | Root proposes, kernel freezes |
| `ValidationResult` | Deterministic evaluation of a frozen ProofSpec | Validation engine |
| `Decision` | The sole canonical mutation transaction | Kernel |
| `Branch` / `Stop` | Explicit lineage or termination decision | Root proposes |

Phase is not a lifecycle state. A Node has one Phase for navigation, while
Attempts and calculations remain inside that Node. A changed question,
principal deliverable, or independent hypothesis branch creates a new Node;
same-question retries remain Attempts. Claims can be tested by multiple Nodes.

`CapabilityRequest` and `ObservationCandidate` are not new canonical registries
or peer graph objects. The request is compiled into the existing calculation or
activity intent journal; candidates live in the parser result until Root either
promotes them to Observations or records why they were not used. This keeps the
loop traceable without adding another state machine.

The normal identifiers are readable workspace ordinals (`phase_1`, `claim_1`,
`node_1`, `calc_1`, `op_1`, `obs_1`, `fnd_1`, `proof_1`, `result_1`). Workspace identities,
content projections, revisions, and digests remain opaque machine bindings and
are not presented as research names.

### 4.1 Two output channels

An Agent turn has two deliberately different channels:

1. **Narrative channel**: reasoning, explanation, uncertainty, and proposed
   alternatives. It is useful to the user and the next context projection but
   has no authority to mutate state or claim that an effect occurred.
2. **Typed proposal channel**: a validated `ts_change`, `ts_calc`, `ts_review`,
   or other public tool call. Only this channel can request a mutation or an
   external effect, and the host supplies identities, paths, receipts, and
   deterministic results.

The host never extracts a Decision, evidence, or success verdict from prose.
Malformed typed output is returned as a structured tool error; no fields are
partially merged, and a bounded repair may retry the same proposal. Provider
transport errors remain provider errors rather than being relabeled as a model
contract failure.

## 5. Hypothesis--Proof Loop

### Step 0: Read a bounded frontier

`ts_state` returns a compact frontier or delta projection containing active
Nodes, Claim status, unresolved Findings, available capabilities, and the
latest relevant observations. Full logs and source files are fetched only on
demand.

### Step 1: Register a testable question

The Agent states:

- one unresolved question;
- the hypothesis or competing hypotheses;
- expected observations and assumptions;
- at least one possible falsifier for a claim that is intended to be tested;
- scope, uncertainty, and a proposed principal deliverable.

Exploratory ideas may remain provisional, but they cannot be presented as
validated claims without an observable prediction and a failure interpretation.
The pre-registration snapshot is digest-bound before result interpretation.

### Step 2: Open a decision-sized Node

The Agent proposes a Phase reference, Claim scope, dependencies, and one
bounded objective. The kernel checks topology and allocates the Node. It does
not derive the Node from a domain label or a Gate result.

### Step 3: Propose a capability action

The request contains a capability ID/version, logical input artifact references,
typed parameters, expected output roles, Claim/Node refs, and a short rationale.
Physical paths, filenames, job IDs, and operation IDs are host-generated.

Example:

```json
{
  "capability": "gaussian.opt_freq",
  "capability_version": "1",
  "node_ref": "node_1",
  "claim_refs": ["claim_1"],
  "inputs": [{"artifact_id": "art_1", "role": "gaussian_input"}],
  "parameters": {"route": "M062X/6-31G(d) Opt Freq"},
  "expected_outputs": ["program_output", "optimized_geometry", "frequencies"],
  "rationale": "Test the pre-registered stationary-point prediction."
}
```

The example is illustrative, not a fixed chemistry recipe.

### Step 4: Kernel preflight

The kernel checks only generic facts:

- capability exists and its version is available;
- parameters satisfy the capability schema and resource limits;
- input artifacts exist, have the requested roles, and match their digests;
- the Node and Claim are writable in the current revision;
- the caller has authority for the declared effect;
- retries and external effects are idempotent or explicitly ambiguous;
- expected output roles are compatible with the parser adapters.

If a capability is unavailable, the kernel returns a structured capability gap.
It does not silently choose a nearby method or reinterpret the hypothesis.

### Step 5: Execute and journal

The executor creates deterministic directories and names, runs the bounded
operation, stores stdout/stderr/receipts, and records scheduler uncertainty.
An HTTP success or a returned job ID is never by itself scientific evidence.

### Step 6: Parse into candidates

Deterministic parsers verify normal termination, route consistency, numerical
fields, and source digests. They emit `ObservationCandidate` records and
diagnostics. A parser cannot invent a scientific conclusion and a failed or
missing output remains a visible Finding.

### Step 7: Promote and interpret

The Root Agent reviews candidates, chooses which semantic observations are
relevant, and submits one `ts_change` transaction with citations and limits.
The kernel verifies artifact digests and provenance. Free text alone never
changes canonical science state.

`ts_change` accepts a high-level mutation proposal. Internally, the kernel
allocates IDs, compiles it to a Decision, runs the complete dry-run validator,
and applies it under the same revision lock. The model never copies a large
compiled Decision between public tools. When an explicit preview is needed,
the kernel returns a short, revision- and digest-bound preview handle; apply
accepts that handle rather than reconstructed JSON.

### Step 8: Freeze and evaluate proof

The Agent may compose a declarative ProofSpec from registered predicates and
observations. The fully expanded specification is frozen before evaluation,
including predicate versions, parameters, selected observation digests, and
the claim snapshot. The engine evaluates it; it never schedules the next
operation.

Proof has two levels:

1. **Universal integrity**: fixed checks such as artifact digest, parser
   provenance, program termination, reference consistency, and transaction
   validity.
2. **Hypothesis-specific evidence**: a Root-proposed ProofSpec assembled from
   generic predicates and, where genuinely required, maintained scientific
   predicate plugins.

The generic registry should first cover composable observation operations such
as existence, absence, equality, ranges, counts, set membership, comparison,
and all/any aggregation. A new scientific question usually composes these over
new observation concepts. Only an analysis that cannot be represented by
these operations requires a maintained predicate plugin.

`pass`, `fail`, `inconclusive`, and `error` remain distinct. A pass means that
the declared evidence standard was met, not that a chemical theory is proven
in the absolute sense.

### Step 9: Record the next decision

The Agent explains what the result supports, weakens, contradicts, or leaves
unknown, then proposes a dependent Node, a new branch, a backtrack, or an
explicit stop. A failed gate does not implicitly launch a calculation.

## 6. Capability Contract

Replace strategy routing metadata with self-describing capabilities. A minimal
descriptor is:

```json
{
  "capability": "gaussian.opt_freq",
  "version": "1",
  "input_schema": "gaussian_input",
  "parameter_schema": "...",
  "produces": ["program_output", "optimized_geometry", "frequencies"],
  "effects": ["local_prepare", "local_parse", "remote_compute"],
  "limits": {"max_atoms": 500, "max_runtime_seconds": 86400},
  "parsers": ["gaussian.log/1"]
}
```

Remove the current `CANDIDATE_STRATEGIES_BY_TASK` table from the machine-facing
catalog in `packages/ts-agent-kernel/ts_agent/compute/capabilities.py`. Optional examples such as
"QST2 is often useful when both endpoints are known" belong in human-readable
recipe/reference material. They are non-authoritative, may be ignored by the
Agent, and must never become permission or routing metadata.

Capability gaps are first-class operational results:

```json
{
  "status": "rejected",
  "reason": "capability_unavailable",
  "requested": "surface_hopping",
  "missing_capability": "excited_state_dynamics",
  "retryable": false
}
```

The Agent can then choose another test, record an unresolved Finding, request
a maintained plugin, or stop. Unknown science is preserved rather than forced
into an existing Gate.

## 7. Falsifiability And Traceability

### Falsifiability requirements

- Store predictions and falsifiers before the relevant result is interpreted.
- Bind each capability request to the Claim dimension it is intended to test.
- Record negative results and contradictory observations, not only supporting
  values.
- Distinguish `unsupported`, `contradicted`, `inconclusive`, and `not tested`.
- Do not let a post-result ProofSpec replace an earlier preregistered standard;
  mark it as a new specification with a new digest.
- Review may suggest a counter-test or a new dimension, but only Root can adopt
  it through `ts_change`.

### Traceability chain

Every scientific conclusion must be traversable in both directions:

```text
Claim
  -> pre-registration snapshot
  -> ResearchNode
  -> CapabilityRequest journal
  -> CalculationIntent/Attempt
  -> Artifact + digest
  -> parser + parser version
  -> Observation / Finding
  -> frozen ProofSpec
  -> ValidationResult
  -> Root Decision / acceptance snapshot
```

The reverse path from an artifact or failed operation must identify the owning
Node, Claim scope, action intent, source digest, and resulting interpretation.
Operational records never become evidence merely because they exist.

## 8. Public Tool Naming

Public names should describe the user action and authority, not internal
schema generations or implementation stages. The target surface is:

| Public tool | Responsibility |
| --- | --- |
| `ts_state` | bounded frontier, delta, capability, and validation projections |
| `ts_change` | the sole canonical mutation boundary; compile/dry-run/apply stay internal |
| `ts_calc` | bind and run one capability action or inspect its result |
| `ts_review` | bounded advisory review |
| `ts_reply` | Root disposition of advisory output |
| `ts_remote` | bound remote transport, readiness, and scheduler effects |
| `ts_seed` | deterministic structure seed |
| `ts_import` | bounded input/artifact import |
| `ts_compare` | deterministic structure comparison |
| `ts_render` | deterministic visualization |
| `ts_report` | deterministic report package |
| `ts_notify` | configured notification delivery |

Internal names such as `ts_workspace_decision_validate`, transaction stages,
or schema versions remain implementation details. A public tool returns a
structured success or failure; it does not ask the model to infer whether a
free-text response was executed.

Calculation intent remains the owner of a scientific calculation. Its executor
may call the `ts_remote` transport capability for upload, submit, status,
collection, or cancel. `ts_remote` therefore remains a real remote subsystem,
but every effect must be bound to an immutable intent, Node, policy, and
receipt; it is never an arbitrary shell or free-form scheduler surface.

The minimal human command surface remains:

```text
/ts          compact current research state
/ts-check    validate the workspace and release contracts
/ts-remote   inspect remote execution readiness
/ts-runs     browse durable Compute/Review history
```

## 9. Context And Subagent Policy

The loop is scientific, but the context supplied to each model must stay
bounded:

- default Root context is a frontier/delta projection, not every file;
- action prompts contain logical artifact IDs and roles, not whole logs;
- Review receives a Claim dossier plus on-demand, digest-bound excerpts;
- Compute receives one immutable action plan and cannot choose chemistry;
- Render, Report, Remote, Import, and Notify remain deterministic host tools;
- summaries are derived projections and never replace canonical records.

Subagents are context and authority boundaries, not additional scientific
routers. They may reduce token use and isolate operational failure, but the
Root Agent remains responsible for the hypothesis--proof loop and the final
interpretation.

## 10. TS Web Design In The Unified Package

TS Web should present the loop directly:

1. **Research Map**: Phase -> Claim lane -> Node, with one question and one
   principal deliverable per Node.
2. **Node detail**: hypothesis, predictions, falsifiers, dependencies, Attempts,
   calculations, artifacts, observations, findings, proof coverage, and final
   decision.
3. **Loop timeline**: Question -> Action -> Execution -> Observation -> Proof
   evaluation -> Decision. This is a projection, not a second event store.
4. **Audit views**: exact DAG, immutable history, digests, failures, and
   unresolved capability gaps.

The Web must not infer a next action, alter a Claim, close a Node, or turn a
passing display badge into acceptance. Buttons exist only for actions backed by
an authenticated TSPi command; read-only rows are visibly read-only.

Web state is external registry/configuration plus a read-only projection of
workspace state. It is never stored inside the scientific canonical files.

## 11. TS Phone Design In The Unified Package

TS Phone remains a companion interface:

- the TSPi host owns scientific state and mutation authority;
- the Phone server authenticates and multiplexes workspace/session views;
- the mobile app displays conversation, loop timeline, model/context metadata,
  and recovery state;
- controller and observer sessions remain distinct;
- stale commands fail on session revision mismatch;
- Phone cannot submit arbitrary paths, shell commands, or direct state writes.

The package builder binds:

- Agent/kernel release and wheel digest;
- Web assets and launcher;
- Phone server archive and launcher;
- API, event, and bridge protocol versions;
- signed mobile APK descriptor and certificate digest.

The installer verifies the complete manifest and atomically selects one suite
release. Configuration, credentials, workspace data, phone tokens, and service
activation remain outside immutable release payloads. A Phone component may be
developed and tested alone, but it is not installed as a competing production
`current` release.

## 12. Implementation Sequence

This branch is a clean redesign branch. Do not add aliases that preserve every
old schema or public name while the new contract is being defined.

### Milestone A: contract inventory and freeze

- inventory all current canonical records, tool names, projections, and release
  manifests;
- identify every scientific `if/else` route and classify it as kernel safety,
  capability implementation, or forbidden scientific policy;
- classify every schema field as fixed envelope or open scientific payload and
  reject fields that mix both responsibilities;
- define one current contract family and remove transitional generation labels
  terminology from user-facing documentation;
- publish the vocabulary and ownership table above as the source of truth.

### Milestone B: generic action and capability kernel

- add a versioned capability descriptor and registry;
- implement typed CapabilityRequest preflight and structured capability gaps;
- make input/output roles and effect policies declarative;
- remove candidate-strategy labels from the machine capability catalog;
- ensure capability metadata cannot select a successor Node;
- add tests showing a new Claim string does not require a core code change.

### Milestone C: hypothesis and observation contracts

- add preregistered predictions/falsifiers and Claim snapshots;
- introduce ObservationCandidate -> explicit Root promotion;
- bind parser versions and artifact digests through the full chain;
- preserve negative, contradictory, missing, and inconclusive outcomes.

### Milestone D: loop runtime

- implement the bounded frontier/delta context;
- make `ts_change` the single public mutation boundary;
- move compile, ID allocation, dry-run validation, and atomic apply behind that
  boundary, with optional digest-bound preview handles;
- keep Compute isolated and zero-choice after action binding;
- keep Review advisory and require an explicit Root reply;
- enforce total time, token, retry, and active-Node budgets without choosing
  scientific strategy.

### Milestone E: validation engine

- keep ProofSpec as the sole public validation specification name; do not expose
  two public names or maintain parallel schemas;
- freeze specifications before evaluation;
- allow Agent-composed dimensions from registered predicates;
- return unsupported-predicate/capability gaps without routing to another test;
- test post-result standard changes as new immutable specifications.

### Milestone F: Web and Phone projections

- expose the loop timeline and Node-first navigation in TS Web;
- expose the same projection through Phone timeline APIs;
- remove duplicated status/widget mutation logic;
- bind both clients to the suite protocol manifest and release ID;
- test stale sessions, pagination, refresh, theme, and read-only boundaries.

### Milestone G: package and release

- make the TSPi suite manifest the only production release authority;
- build Agent and any selected Web or Phone component from clean component sources;
- verify nested digests, protocol compatibility, permissions, and launchers;
- run source, package, runtime, Web, Phone, and end-to-end loop tests;
- document install, configuration, rollback, and component development paths.

## 13. Acceptance Criteria For This Refactor

The redesign is complete only when all of the following are demonstrated:

- an unknown Claim type, observation concept, or validation dimension is
  recordable without a hard-coded route;
- an unavailable capability yields a precise gap and never silently substitutes
  another calculation;
- adding a maintained capability plugin does not edit a hypothesis dispatch
  table;
- a gate/proof failure never automatically starts a calculation;
- predictions and falsifiers are immutable before interpretation;
- every accepted observation and validation result has a complete digest-bound
  provenance chain;
- failed, ambiguous, and missing remote effects remain visible and are not
  replayed blindly;
- Root free text cannot mutate canonical science or manufacture evidence;
- context size is bounded and measured for Root, Compute, Review, Web, and
  Phone projections;
- TS Web and TS Phone render the same authoritative loop without becoming state
  owners;
- one TSPi package installs a version-compatible Agent and selected Web/Phone components and can
  be rolled back atomically.

## 14. Risks And Deliberate Controls

| Risk | Control |
| --- | --- |
| Agent explores forever | explicit resource/time/turn budgets and an explicit stop operation |
| Agent submits unsafe parameters | capability schemas, effect authority, limits, and sandboxing |
| Model treats parser output as proof | Candidate/Observation/Validation separation |
| Standards are lowered after seeing results | preregistration, frozen ProofSpec digests, immutable history |
| Open vocabulary becomes incoherent | typed relations, provenance, Findings, and advisory Review |
| Plugin proliferation recreates routing | capability descriptors; no domain dispatch in the kernel |
| Web/Phone drift from Agent | one suite manifest and protocol compatibility checks |
| Context grows with every loop | frontier/delta projections and on-demand artifact reads |

The central invariant is:

> Fix the language of safe, auditable actions; keep the language of scientific
> questions open; let the Agent choose the question and the kernel verify the
> consequences.
