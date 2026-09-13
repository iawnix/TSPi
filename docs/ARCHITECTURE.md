# TSPi Architecture

[English](ARCHITECTURE.md) | [简体中文](ARCHITECTURE.zh-CN.md)

This guide explains how TSPi organizes research sessions, runs calculations,
validates conclusions, and presents results through terminal, Phone, and Web.
Field definitions live in the implementation's JSON/TypeBox schemas.

## System Shape

TSPi connects a Pi research session to scientific tools, workspace records, and
terminal, Phone, and Web interfaces.

```text
Terminal / TS Phone
  -> TSPhoneServer (Host)
     -> one active Worker per workspace
        -> Pi + Skills + extensions
           -> Root Agent -> Research Kernel -> scientific records
           -> Compute / Review -> tools and journals
           -> Validation Engine + Context Compiler
           -> molecular figures, curves, and reports

TSPi --standalone -> native Pi with the same research tools
TS Web -> projection provider -> workspace records and calculation history
```

Root selects questions, hypotheses, methods, branches, interpretation, and
stopping conditions. Compute carries out a selected calculation plan. Review
assesses a Claim from a separate session. Host tools implement state
transactions, calculations, structure operations, rendering, and delivery.

## Components And Installation

The GitHub installer builds TSPi and selected extensions, configures the
installation, and optionally enables and starts systemd services.

| Component | Source | Installed use |
| --- | --- | --- |
| TSPi Agent | `packages/`, `extensions/`, `skills/` | Research sessions and scientific tools |
| TS Web | `components/ts-web/` | Browser explorer using the TSPi projection provider |
| TS Phone | [ts-phone repository](https://github.com/iawnix/ts-phone) | Shared terminal/Phone Host and Android client |

`scripts/install_phone.py` fetches Phone source, builds its server with npm,
and records the commit, protocols, and runtime file hashes in
`.pi/ts-phone/releases/<commit>/installation.json`. The
`.pi/ts-phone/current` pointer selects the server. The wizard checks its
protocols against the selected TSPi version before activation.

The package builder assembles Agent and optional Web/Phone archives into
`tspi-package-release/4`. An APK-inclusive Phone archive uses
`ts-phone-component-release/2`, including the signed APK, source snapshot, and
attestation binding its source, digest, version, build, ABI, and signer.
The Android client is installed on the device.

The package installer captures the archive in staging, checks manifests and
digests, extracts components, prepares the Python runtime, and selects:

```text
<installation>/.pi/packages/tspi/current
```

Stable entrypoints `TSPi`, `TSWeb`, `TSPhoneServer`, and `TSPhoneCtl` resolve
the selected release. Phone entrypoints load a bundled server when present,
otherwise the server selected by `.pi/ts-phone/current`. They verify the
selected server before import.

Configuration, model credentials, SSH settings, notification settings, Phone
tokens, Pi sessions, workspaces, and service state are stored separately from
release files. Upgrades retain them. The shared dotenv reader applies explicit
environment values, then installation configuration, then defaults.

See [Installation and Operations](INSTALLATION.md) for setup, service
management, upgrades, rollback, and uninstall.

## Python Runtime

`pyproject.toml` builds `ts-agent-kernel` from
`packages/ts-agent-kernel/ts_agent/`. The Agent builder creates a wheel in a
temporary source copy and embeds it under `python-dist/`.
The `ts-agent-release/2` manifest records its name, version, size, SHA-256,
and expanded payload digest.

The runtime store has two layers:

| Location | Contents |
| --- | --- |
| `base/<spec-hash>` | Shared Conda scientific and rendering dependencies |
| `kernels/<payload-hash>` | A venv using the base and the selected kernel wheel |

A dependency change prepares a new base; a kernel change prepares a new
overlay. The runtime probe verifies installed module and data hashes,
NumPy/RDKit origins in the base, and the kernel distribution in the overlay.
The `ts-agent-runtime/2` manifest binds these origins and capabilities.

Activation follows prepare, probe, publish. Preparation failures keep the
selected release. Publication failures restore the previous manifest, pointer,
install state, and stable links. Prepared releases remain available for retry.
Service restart is handled by the installer wizard or operator.

## Component Responsibilities

| Component | Responsibility | Output |
| --- | --- | --- |
| Lifecycle host | Select release, initialize workspace, hold writer locks, start Pi | Process and session identity |
| Root Agent | Choose and interpret research actions; submit `ts_change` | Conversation and Decisions |
| Research Kernel | Validate and commit scientific records | Registries, transactions, acceptance records |
| Context Compiler | Select relevant graph context | Revision-bound projections |
| Validation Engine | Compile and evaluate ProofSpecs | Frozen checks and ValidationResults |
| Compute Agent | Execute a Host-bound calculation plan | Action receipts and run result |
| Review Agent | Assess a Claim and selected artifacts | Advice and Root disposition |
| Deterministic tools | Prepare inputs, run calculations, analyze, render, report, notify | Artifacts and operational journals |
| TS Phone Host | Manage conversations and dispatch messages to Workers | Sessions, queues, command receipts |
| Terminal and Phone clients | Send messages and display the shared conversation | Interactive conversation view |
| TS Web | Browse scientific records and calculation history | Research map, details, and file previews |

After workspace initialization, scientific changes pass through `ts_change`
and the Kernel transaction validator. Tool outputs become scientific records
when Root verifies their source artifacts and records Observations or Findings.

## Scientific State Model

| Record | Meaning |
| --- | --- |
| ResearchPhase | A title and objective grouping related research questions |
| ResearchNode | One research question, its deliverable, dependencies, Claim scope, and outcome |
| Claim | A scientific statement with assumptions, falsifiers, status, and evidence references |
| ClaimRelation | A named relationship such as dependency, refinement, conflict, or alternative |
| Observation | An immutable typed scientific value with units, qualifiers, and artifact provenance |
| Finding | An anomaly, limitation, conflict, or unresolved question with severity and resolution |
| ProofSpec | A frozen set of declarative validation checks |
| ValidationResult | Predicate outcomes and aggregate verdict over selected Observations |
| Acceptance | An immutable assessment of a Claim against an acceptance profile |

Every Node belongs to one Phase. Node dependencies form a DAG: one predecessor
supports continuation, several support merging, and an edge to an earlier
checkpoint supports backtracking. Earlier Nodes and Attempts retain their
history. Root chooses the next question from this history and current evidence.

One Node owns one principal question and deliverable. Retries and parameter
variations answering that question remain Attempts. A changed question,
independent hypothesis branch, or principal deliverable starts a dependent Node.
Claims hold hypotheses, assumptions, and falsifiers so several Nodes can test
the same statement.

ClaimRelations form a directed acyclic graph. Their labels describe the
scientific relationships between statements.

`ResearchNode.claim_refs` records declared scope;
`Claim.created_by_node` records origin. Read views use their union to show
Claim-Node relationships. Research Trajectory joins Nodes to opening and
completion Decision summaries for context, Web, and reports.

The Kernel allocates readable workspace-local ordinals such as `claim_1`,
`rel_1`, `node_1`, `obs_1`, `fnd_1`, `proof_1`, `result_1`, and
`acc_1`. Revisions and content digests bind record versions. Scientific types,
tags, relation labels, concepts, and validation dimensions use open vocabulary;
executable contracts define enums for statuses, data types, and verdicts.

## Canonical And Operational State

Scientific records determine `workspace_revision`:

```text
workspace.json
research_state.json
phases.json
claims.json
claim_relations.json
research_nodes.json
observations.json
proof_specs.json
validation_results.json
findings.json
acceptances/<acceptance_id>.json
decisions/<decision_id>.json
decision_log.jsonl
transaction_log.jsonl
```

Calculation Attempts, Compute/Review runs, tool activities, reports, remote
receipts, and notification receipts provide operational history and contribute
to `operational_revision`. Operational IDs use `calc_n`, `sub_n`, and
`op_n`, allocated under a lock with a monotonic high-water mark.

`workspace.operational.calculation_attempt_index()` validates intent,
preparation, status, and result bindings. Context, API, Web, and file views share
its Attempt rows and integrity findings. An unreadable or unsafe parent
directory produces a `scope=attempt_parent` diagnostic. Symlink entries
produce diagnostics and stop traversal.

Interfaces display workspace labels and readable record IDs. Workspace
identities, projection IDs, revisions, and digests are available as technical
details for tracing records.

## Decision Transaction

```text
ts_state -> Root decision -> ts_change -> compile -> validate -> commit
```

Root submits ordered operations with local aliases. For an unfamiliar
operation, `ts_state mode=change_contract operation=<op>` returns its fields
from the compiler's operation registry.

The Kernel allocates IDs, resolves aliases, compiles ProofSpecs, and evaluates
requested validation against a proposed state. It checks the complete
post-state under the workspace lock and commits one `ts-research-decision/3`
bound to the current scientific revision. Replaying the same complete request
digest returns the recorded transaction.

Supported operations are:

```text
create_phase          create_claim          relate_claims
start_node            complete_node
record_observation    record_finding        resolve_finding
freeze_proof_spec     evaluate_proof
update_claim          accept_claim          set_focus
```

One Decision can start at most one Node and complete at most one Node. It can
start and complete the same Node; closing one and opening another together
requires a successor edge. Root usually sets focus when opening active work.
Focus records navigation, while Claim and validation records express scientific
interpretation.

## Validation Engine

Claim closure uses ProofSpec, ValidationResult, and Acceptance:

1. Select a versioned proof template or compose registered predicates.
2. Freeze checks, parameters, template digest, and predicate-registry digest.
3. Evaluate against explicit Observation references and content digests.
4. Review the verdict and record the Claim's interpreted status.
5. Run `accept_claim` with the relevant acceptance profile.

| Verdict | Meaning |
| --- | --- |
| `pass` | The declared checks are satisfied |
| `fail` | Valid inputs fail one or more required checks |
| `inconclusive` | Available valid inputs leave the question undecided |
| `error` | The declared checks could not be executed |

Acceptance requires a supported Claim, at least one ProofSpec, required
dimensions, coverage of all attached ProofSpecs, their latest passing results,
matching digests, and resolved applicable blocking Findings. The acceptance
record binds the Claim, profile, specifications, results, and Findings.
Its `acceptance_digest` binds the full record; comparison with current state
determines whether that assessment is still current.

For a classical transition state, stationary-point, imaginary-mode, and
connectivity checks answer different questions. Electronic-state, thermochemical,
or robustness requirements depend on the Claim and profile. Crossing and
dynamics studies can use additional maintained templates and predicates.

Definitions are declarative combinations of registered predicates. Adding a
new calculation or scientific check requires maintained implementation, tests,
and an updated registry digest. Detailed validation guidance lives in
[the orchestration Skill](../skills/tspi-orchestration/SKILL.md) and the
relevant method Skills.

## Context Compiler

The compiler provides revision-bound projections:

| Mode | Contents |
| --- | --- |
| `frontier` | Focus, alternatives, dependencies, open Findings, incomplete validation, recent changes |
| `claim`, `node`, `finding`, `proof` | One object and its relevant neighborhood |
| `subgraph` | A caller-selected graph to a bounded depth |
| `delta` | Changes since known scientific and operational revisions |
| `locate` | Current objects and artifact locations matching an ID or text query |
| `artifacts` | Registered logical artifacts and bindings |
| `capabilities` | Available compute and validation contracts |

Bounded views include omitted counts and retrieval hints. Claim artifacts are
resolved through direct Observation references. Attempt views distinguish
input bindings from output artifacts. The compiler rebuilds views on demand.

The compact `workspace_brief` includes Node trajectory. Web and reports use
the same trajectory derivation. Exact proof template discovery returns its
accepted parameters and Observation selectors before drafting a ProofSpec.

## Read-Only Web Projection

TS Web reads the TSPi provider protocol. Its registry maps display labels to
workspace sources and lives outside research workspaces. Installation discovery
reconciles direct children of `<installation>/workspaces`, preserves manual
registrations, and retains the registry if discovery fails.

One snapshot request normalizes the workspace and returns revisions; when
changed, it also returns View and Graph from that same pass. Browser polling
pauses when hidden and preserves the current selection.

Research Map groups work by Phase and Claim. Lane assignment uses a primary
Claim, then a sole derived Claim association, then an unassigned lane.
Connectivity observations appear with their producing Node and use explicit
`connectivity_direction` qualifiers for direction. Dependency DAG shows
cross-Phase edges, branches, merges, and backtracking.

Node details include conclusions, evidence, calculation families, activities,
files, and Decision history. Runs show purpose, retry/recalculation relations,
settings, remote resources, timing, and artifacts. Scientific Conclusions
offers Table and Map views of Claims and ClaimRelations.

The HTTP API provides read operations. File previews resolve admitted Node
files and recheck containment, regular-file status, UTF-8 encoding, and size
when opened. Run the service on loopback or a trusted firewalled network; network
access control is provided by the deployment.

Installed Web processes watch the stable `TSWeb` target. Once a new selected
release and runtime are ready, the process closes its socket and executes the
stable command to load that version.

## TSPi Lifecycle

The default `TSPi` command starts `apps/terminal/index.mjs`, which connects
to the authenticated Host. `--phone` selects the same route.
`--standalone` starts native Pi. The launcher selects Pi through `PI_BIN`
or the first `pi` on `PATH`.

The Host addresses a conversation by `workspaceId + sessionId`. Clients share
its Worker, event stream, and command receipts. Opening history loads records;
sending a queued request activates execution. The Host serializes turns per
workspace and deduplicates client message IDs.

Native Pi and Host Workers follow this lifecycle:

1. Resolve the installation and selected release.
2. Load runtime, remote, notification, and cache configuration.
3. Verify the isolated Python runtime and kernel payload.
4. Resolve the workspace and hold its session-directory guard.
5. Acquire the workspace Root lock and the exact session writer guard.
6. Initialize a fresh workspace or validate existing scientific records.
7. Start Pi with the package's Skills, extensions, and theme.

One Root writer owns a workspace at a time. Different workspaces run
concurrently with separate sessions and research data. Shared directory guards
and exclusive session guards remain held throughout Pi execution. Held OS
locks establish ownership; guard files retain descriptive PID information.

Host-managed Workers use Pi SDK/RPC through
`extensions/ts-phone-bridge/runtime.mjs`. Saved session model selection takes
precedence over startup preference. Credentials and the model registry live in
`PI_CODING_AGENT_DIR`, defaulting to `~/.pi/agent`. Model changes apply to
the conversation and future queued requests.

`--continue` selects the latest conversation; `--session-id` selects an exact
one. Reopen native sessions through the launcher to switch or fork. Completing
a ResearchNode updates the workspace while the conversation can continue.

## Phone Sessions And Recovery

Phone Controller messages use the same research tools as terminal messages.
Observer sessions use a read-only tool set. The Bridge publishes model readiness
and safe prompt errors alongside connection status.

Queue admission persists a request and its model selection before acknowledgement.
A Host restart retains waiting requests and marks interrupted execution
`unknown`. Inspect history, outputs, and Worker state before acknowledging an
uncertain request. Direct receipts and the event delivery cache are bounded
in-memory records. SSE reconnects use a current snapshot when a cursor is too old.

Phone management stores display names, preferences, and lifecycle revisions in
`management.json`; Pi stores conversation JSONL. Before project or session
deletion, the Host performs `--lifecycle-preflight` and holds
`--lifecycle-guard`. Active writers, remote calculations, unresolved controls,
and integrity errors must be settled before deletion.

The installation records `tspi-session-guard/1`. Worker registration verifies
the spawned PID, launch identity, and held locks; startup failures return fixed
codes such as `session_writer_active` and `session_guard_upgrade_required`.
The installer establishes this contract during upgrade with workspace locks
and process inspection. Run that upgrade after existing writers exit.

Host activation reserves one launch per workspace and completes on a model-ready
snapshot. Terminal disconnect detaches a client; `/abort` stops generation;
Worker shutdown and remote calculation cancellation are separate actions.
See [Terminal Client](TERMINAL.md) for commands and receipt recovery.

## Public Extensions

| Extension | Tools and commands | Purpose |
| --- | --- | --- |
| `ts-workflow-control` | `ts_state`, `ts_change`; `/ts`, `/ts-check` | Research context and state transactions |
| `ts-workflow-review` | `ts_review`, `ts_reply` | Claim review and response |
| `ts-workflow-compute` | `ts_calc`, `ts_remote`; `/ts-remote` | Calculation lifecycle and remote diagnostics |
| `ts-workflow-artifacts` | `ts_seed`, `ts_compare`, `ts_import`, `ts_render`, `ts_report`, `ts_notify` | Inputs, analysis, figures, reports, delivery |
| `ts-workflow-ui` | `/ts-runs` | Activity and run history |

`ts-phone-bridge` is loaded for Host Workers and `--standalone --phone`.
The [Skill catalog](../skills/README.md) describes method guidance and when
to load it. Tool schemas define call fields; capability catalogs describe
adapter tasks, proof templates, predicates, and profiles.

## Isolated Agent Runtimes

Compute and Review each start a fresh in-memory Pi session with the selected
model identity, a scoped task, and an explicit tool set. Host validation checks
results locally, allows one structural repair, and reports provider errors
before output-format errors.

### Review

The Host prepares a Claim dossier containing relevant relations, Nodes,
Observations, Findings, ProofSpecs, ValidationResults, and an artifact manifest.
Review receives this dossier in place of the parent transcript. Its tools are
`ts_review_result` and, when selected artifacts are available, one batch
`ts_review_artifact_read` call.

The Host checks artifact ownership, containment, size, digest, and read budgets.
It journals excerpt metadata and validates result identity, scope, and citations.
After a successful Review, Root records one `ts_reply` before the next
scientific mutation, then verifies primary evidence for any adopted advice.

### Compute

A `ts-agent-task/2` binds one Node, one immutable intent digest, and one plan:

```text
launch   prepare -> submit
inspect  status -> optional tail
finalize collect -> parse
cancel   cancel
```

The Host validates paths, identities, digests, backend, and execution target
before starting the child. Each zero-argument action tool is bound to that
request and executes once after its prerequisites. Unknown submit/cancel effects
require reconciliation. The model supplies summary and limitations; the Host
derives outcomes, artifacts, and reconciliation flags from action receipts.

## Deterministic Tool Plane

### Calculations

The compute kernel implements preparation, submission, status, tail, collection,
cancellation, and parsing. `ts-calculation-intent/7` binds Node, input artifact
IDs and roles, backend/task/parameters, target, and expected outputs. Retries
preserve the scientific-intent digest; recalculations change it and record the
changed fields. Both refer to an earlier Attempt in the same Node.

The `local` target supports preparation and parsing with `dry_run=true`.
Remote execution uses the installation's SSH/Torque profile. Submit stages
inputs and control records; inspect reads scheduler/program status. Finalize
downloads declared outputs according to the manifest and parses them locally.
Collection works from the manifest even when queue history is unavailable.

### Structures And Inputs

`ts_seed` generates an initial geometry from one connected SMILES with declared
charge and multiplicity. RDKit ETKDGv3 uses a fixed seed, explicit hydrogens,
charge/electron-parity checks, and optional UFF initialization. It records XYZ
and provenance. Follow-up calculations establish stationary-point properties.

`ts_import` accepts inline Gaussian, XYZ, or xTB control input, checks metadata
and format, and returns a content-addressed Node artifact. Identical content
reuses that artifact.

`ts_compare` compares two registered XYZ artifacts with optional zero-based
atom mapping, reaction-center selection, internal coordinates, stereochemical
checks, and RMSD thresholds. Its JSON output records metrics and provenance.
Root verifies values before recording scientific Observations.

### Figures And Reports

`ts_render` creates molecular PNGs, trajectory GIFs, comparison panels, and
reactant/transition-state/product diagrams with `xyzrender`. Operations
`curve`, `energy`, `scan`, and `convergence` use Matplotlib to render one
`ts-curve-data/1` JSON artifact to PNG. Input units, labels, and energy
references travel with the curve data.

Each render uses a new Node-owned output filename. `ts_report` creates a new
report package, checks revisions and file digests, and copies selected PNG/GIF
artifacts with an `asset_index.json`.

### Notifications

`ts_notify` delivers configured research events through ClawEmail. The
installation's `notifications.toml` provides recipient and credentials.
Attachments are verified members of a `ts-report-package/4` manifest.
Receipts identify successful deliveries; unknown provider outcomes require
inspection before another delivery.

## Run Journals And Result Delivery

```text
nodes/<node_id>/attempts/<calc_id>/runs/<sub_id>/
reviews/<claim_id>/runs/<sub_id>/
```

Compute journals belong to an Attempt; Review journals belong to a Claim.
Creation writes an immutable task and snapshot. Terminal handling records
actions, result or failure, and final run state. A crash can leave a task-only
journal pending/unknown. Recovery checks action receipts and outputs.

Deterministic tools write Activity Journals with `node_refs`. A shared index
checks ownership, paths, and status/result consistency and builds Node views.
Tool returns deliver results to Root; `/ts-runs` reads durable summaries.

Node completion requires settled owned operations, consistent journals,
resolved compute controls, and completed collection/parsing. Intent-only and
prepared Attempts can be abandoned before an external effect. Every subsequent
status, result, control, run, or output record requires a valid
`prepared.json` binding.

Attempt states `failed`, `stopped`, and `parsed` are settled.
`submitted`, `queued`, `running`, `completed`, `collected`, `missing`,
and `unknown` require follow-up before Node completion. A failed scientific
input activity allows `inconclusive`, `blocked`, or `stopped` closure.
A terminal rendering failure is recorded in history while scientific completion
is assessed from the Node's evidence. Analytical Nodes can complete without
tool activity.

## Failure Handling

| Failure | Follow-up |
| --- | --- |
| Before-effect schema, binding, or staging error | Correct the request/configuration; `retry_same_submission` permits retry |
| Missing scheduler reply after submission begins | Preserve the job ID and reconcile receipts, scheduler state, and outputs |
| Program or parser error | Inspect the corresponding output and record the failure at its source |
| Scientific contradiction | Record verified Observations and a Finding, then reconsider the Claim |
| Provider HTTP/stream error | Report the provider failure before classifying missing child output |
| Journal or UI serialization error after a completed action | Preserve the action outcome and report the recording/display failure separately |
| Stale revision, digest mismatch, cyclic graph, or incomplete workspace | Stop the transaction, inspect the records, and restore a valid state |

Detailed recovery procedures are in
[program failures](../skills/tspi-orchestration/references/program_runtime_failures.md)
and [remote execution](../skills/tspi-orchestration/references/remote_contract.md).

## Contract Locations

| Contract or feature | Location |
| --- | --- |
| Tool inventory | `extensions/shared/tool-catalog.ts` |
| Tool request schemas | `extensions/ts-workflow-*/index.ts` |
| Agent task/result protocol | `packages/ts-agent-runtime/agent-core/agent-protocol.cjs` |
| Scientific record schemas | `packages/ts-agent-kernel/ts_agent/workspace/contracts/` |
| Decisions and transactions | `packages/ts-agent-kernel/ts_agent/workspace/decision.py` |
| State validation | `packages/ts-agent-kernel/ts_agent/workspace/validator.py` |
| Transaction application | `packages/ts-agent-kernel/ts_agent/workspace/engine.py` |
| Attempt lifecycle | `packages/ts-agent-kernel/ts_agent/workspace/operational.py` |
| Operation fields | `packages/ts-agent-kernel/ts_agent/workspace/operation_registry.py` |
| Context and Review snapshots | `packages/ts-agent-kernel/ts_agent/workspace/context.py` |
| Validation templates, predicates, profiles | `packages/ts-agent-kernel/ts_agent/validation/` |
| Calculation bindings | `packages/ts-agent-kernel/ts_agent/calculation_contracts.py` |
| Backends and parsers | `packages/ts-agent-kernel/ts_agent/backends/` |
| Remote execution | `packages/ts-agent-kernel/ts_agent/remote/` |
| Artifact requests | `packages/ts-agent-runtime/artifacts/request-contract.cjs` |
| Structure analysis | `packages/ts-agent-kernel/ts_agent/structures/` |
| Rendering and curves | `packages/ts-agent-kernel/ts_agent/render/` |
| Report generation | `packages/ts-agent-kernel/ts_agent/report/` |
| Web projection provider | `packages/ts-agent-kernel/ts_agent/projection/` |
| Web server and browser | `components/ts-web/` |
| Terminal and Host entrypoints | `apps/terminal/, apps/host/` |
| Installation and runtime | `scripts/, pyproject.toml` |
