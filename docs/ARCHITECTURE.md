# Architecture

The normative unified Research Harness lifecycle is defined in [ADR 0006](adr/0006-unified-research-harness-lifecycle.md).

[English](ARCHITECTURE.md) | [简体中文](ARCHITECTURE.zh-CN.md)

TSPi packages scientific skills and runtime adapters on top of Pi. One
installation runs one Agent Server: its Host is the API, session, and
transaction host, while the Root Agent/Harness owns the prompt loop, model,
and tools. Each active workspace has one pinned Pi `SessionWorker`/`durable
Harness` lane. The terminal, Phone, and Monitor are clients of that lane; none
owns a second agent loop or replacement UI.

## Component Responsibilities

- `apps/app-server/` contains the Agent Server: the `tspi-host/1` API, Root
  Agent session host, transaction boundary, installation Pi App Server/Harness
  owner, native remote-client launcher, Monitor worker, browser adapter, and
  history migration tools. The pinned Pi worker loads TSPi's
  worker facet (tools, skills, hooks, policy, and system prompt).
- `services/tspi-link-relay/` owns TSPi Link enrollment, pairing, device
  authorization, and opaque frame forwarding. It has no workspace, session, or
  research APIs and does not decode Host RPC.
- `packages/research-state/` owns the canonical `ResearchMap`, admission,
  reference integrity, validation, revisions, and transactions. `packages/research-memory/`
  builds bounded context and session projections. `packages/job-runtime/`
  executes local and remote Jobs; `packages/tspi-runtime/` connects their
  receipts, observations, and collected Artifacts to Research State. The shared Link
  protocol and backpressure codec live in `packages/tspi-link/`; the relay
  service is only its deployment composition.
- `extensions/` contains installable Skills, scientific scripts, registered
  validators, and acceptance profiles. Scientific calculations and analysis use
  Skill scripts through generic Jobs; report formatting and email use Skill
  helpers through native bash. Extension manifests can still declare provider metadata for
  discovery; this inventory does not dispatch scientific execution.
  Package-owned server tool assembly is not an
  external extension; it lives under `apps/app-server/server-tools/`.
- `packages/agent-ui/` contains only the small Native TUI presentation helpers
  required by the client facet. Direct ExtensionAPI adapters and their public
  entrypoints have been removed; they are not selected by the launcher or
  loaded by the Native Pi Worker.
  `apps/app-server/server-tools/` is the sole package-owned tool entry. The App Server
  loads only the allowlisted, digest-verified entries in
  `apps/app-server/server-tools/extensions.json`; the worker also loads package skills,
  hooks, policy, and system prompt once for every transport. It never evaluates
  code supplied by a client.
- `components/ts-web/` is an optional read-only browser client that renders the
  serialized canonical `ResearchMap`. The optional
  `apps/app-server/tspi-browser-gateway.mjs` adapter exposes the same Host
  session to a browser over the versioned session-control contract; it attaches
  to an existing session and never owns a second Worker. The
  `pi-session-control-server.mjs` module supplies the shared HTTP transport for
  that contract.
- TS Phone is an independent Flutter client that connects through TSPi Link.

Pi's App Server/Harness owns the session directory, transcript history, model
state, prompt loop, and worker lane. The Host is the same Agent Server's API,
routing, authentication, idempotency, scheduler lease, transaction, and client
subscription layer. The native Pi TUI, Phone, and Monitor address the same lane and therefore see the same
`read`, `write`, `bash`, and package tool inventory; transport is not an
authorization role.

Host RPC is independent of its byte transport. Installed clients use a private
Unix socket; the remote terminal client may start `tspi-host-proxy` over SSH and
forward stdin/stdout to both the remote Host and Pi App Server sockets; Phone
continues to use the TSPi Link WSS Relay. All three use the same `tspi-host/1`
NDJSON protocol and never create a second Agent lane.

The remote Host owns the canonical workspace, SQLite durable sessions, Research
Memory, and workspace locks. TSPi does not use live bidirectional rsync for
workspace operation. Explicit file movement for a remote job remains an
operational shell concern; artifact registration stays separate from transport.

## Scientific State Model

Each research workspace has one filesystem ResearchMap context and one durable lifecycle projection:

```text
workspace_manifest.json     # immutable identity, mode, root, and admission state
research_map/context.json   # canonical ResearchMap scientific records
lifecycle/liveness.json     # lifecycle and decision-needed projection
memory/index.json           # bounded memory projection
nodes/<node_id>/            # optional Node-local working files
runs/jobs/<job_id>/         # staged Job inputs, receipts, logs, and outputs
artifacts/<artifact_id>/    # registered payload and manifest
inputs/                   # workspace-relative imported input artifacts
operations/               # turn, monitor, and execution receipts
```

The canonical scientific records live in `research_map/context.json`.
They include phases, claims, nodes, findings, gates, requirements, Attempts,
Artifacts, and evidence links. `research.map` projects these records into the
`research-map/1` document consumed by clients. Validation and mutation operate
on the canonical JSON records through Research State contracts and ChangeSets.

Attempts record Job execution; Artifacts describe collected or imported material.
Their stable identity, digest, provenance, lineage, and evidence references are
governed by Research State and the Artifact Store. Raw files remain in the
workspace; Research State stores bounded Artifact records and Evidence Links,
and never turns scheduler state or file contents into a Finding or Claim
conclusion by itself.

```text
Job Runtime -> Attempt -> Artifact Manifest
                              |
                              +-> Evidence Link -> Claim/Finding/Gate
```

An Artifact is not a Finding. It is a verifiable data object; an Evidence Link
records whether it supports, contradicts, qualifies, or derives a scientific
object; and a Finding is the Root Agent's scientific statement based on that
evidence. Large logs, trajectories, and images stay out of the ResearchMap and
model context; Agents read bounded manifests, summaries, and on-demand
excerpts.

### ResearchMap And Research State

`ResearchMap` is a research graph with explicit record kinds. A Claim represents
a scientific statement, a Node represents bounded work, and a Phase is an
optional navigation grouping. A Finding uses `kind: fact` for an observation
or `kind: issue` for a problem, contradiction, or risk; its status and cited
evidence are separate fields.

New Claims start as `proposed`. `assess_claim` records a reason and registered
evidence for scientific status changes; imported data and literature can supply
evidence without a new Job. The adopted assessment binds evidence versions and
required ClaimGates. Its projection reports `current`, `needs_review` or
`not_assessed`; historical statuses are not silently promoted to verified assessments.
Evidence or ClaimGate changes can be committed before reassessment. A `needs_review`
assessment prevents terminal closure without freezing independent work.

```text
Claim -> Node -> Finding (kind: fact | issue)
       ^               |                  |
       |               +------ Gate <-----+
       +----------- ClaimGate / NodeGate
```

The Research State filesystem boundary loads, validates, commits, and persists the
canonical workspace projections. The research-state runtime owns this boundary; the Node
App Server exposes only the transport bridge and language-neutral port. The
map-shaped context projection is the canonical serialization for TS Web and Root Agent,
not a second scientific model. The Root Agent chooses questions, methods,
branches, and stopping conditions. Skills describe research procedures and
construct commands for installed scientific software. A named Job environment
selects local or remote execution, executable configuration, and any required
transport and scheduler settings. Tool success
never becomes a scientific conclusion by itself.

### Domain-Neutral Research Harness Lifecycle

The Research Harness is domain-neutral. Chemistry, reaction mechanisms, data
analysis, simulation, and other research domains use the same Claims, Nodes,
Findings, Gates, Attempts, and Artifacts. Domain-specific behavior belongs in
Skills, scientific scripts, validators, and Artifact schemas; it must not be encoded in
Host scheduling or Research State liveness rules.

```text
Agent (only scientific decision-maker)
  -> bounded Research Context -> Research State (canonical ResearchMap)
  -> Harness/Host (turn admission, authority, recovery, follow-up)
       +-> Monitor (external observation and next_run wake-up)
       +-> Job Runtime and Artifact Store (execution and collected material)
```

Durable Research Memory remains in the workspace. Each turn gets a bounded
`research.context` read model containing the current focus and compact runtime
summaries; it is not a second scientific state and does not copy full history
or every Skill into model context. Each category has a fixed item limit and a
fixed text/reference limit and a truncation marker; arbitrary lifecycle-action
metadata and large reference lists are reduced to keys and bounded IDs. Full
records remain available through focused map/detail queries. Skill catalogs are
loaded when a worker is created and Skill bodies are cached for explicit
invocation; names, descriptions, locations, and the `system` scope marker for
the two Core System Skills are placed in the model's default prompt. Compute
Environments are queried when selecting or launching a method.

Before each model request, the worker injects a fresh authoritative projection
as the request-only `tspi_research_context` system section, without adding a user
message or changing conversation history. A state refresh does not start a turn
or require recovery from `continue_required`. The focused view includes compact
records for referenced strategy/Attempt nodes and their dependencies, and
explicitly distinguishes unlisted objects from missing objects.

The worker also detects consecutive context/liveness reads and checkpoints at
the same research revision in the durable transcript. Six such calls produce a
runtime reminder; twelve stop request admission before further generation or
compaction. Checkpoint IDs and changing query limits do not reset this count.
An intervening work/evidence call, changed revision, or actual user input resets
it. This is a narrow control-loop guard, not a scientific progress evaluator;
it does not cancel Jobs or change Research State. State continuation checks the
same history so it cannot immediately restart the stopped loop.

Admission uses Pi's token estimate
(including applicable provider usage), the request's output allowance, and a
4,096-token safety margin. System prompt and tool definitions already present in
the request are not counted again. The projection's 16,000-byte storage limit is
separate from this token budget; telemetry records both units explicitly.
A budget refusal lets the Harness attempt at most one blocking compaction and
then rebuild and recheck the request. Insufficient space after recovery, State
read failures, and projection receipt failures terminate the request with an
explicit error. They never become instructions asking the model to restore its
own snapshot through repeated tool reads.

The generic Job Runtime is the execution boundary. A Skill constructs the
program argv, input files, expected outputs, parser instructions, and method
metadata; `job_start` accepts that bounded argv for either local or remote
execution. There is no scientific provider registry or capability descriptor
gate between a Skill and Job Runtime. Preflight checks the selected named
environment and records its configuration in Job metadata. The same control
path writes canonical workspace Artifacts in both light execution scopes and
research Attempts, so no second ArtifactStore can diverge from the workspace.

The runtime boundary is explicit:

```text
Research Memory (durable records)
  -> ResearchMemoryService (one facade over the canonical store)
  -> ContextBuilder (bounded deterministic projection)
  -> ContextPack (ephemeral turn working set)
  -> Prompt (ContextPack plus tools, Skill metadata, and instructions)
```

The Native worker reads `research.context` through the runtime command boundary.
Pi owns conversational session history; Research State owns workspace scientific
records and their memory projection. Refreshing the bounded context does not
create another state store or session owner.

`ResearchMemoryService` does not cache a second ResearchMap or persist a
ContextPack. `ContextPack.revision` and provenance identify the source
revision so a Host can rebuild it after a change or retry. Semantic writes stay
on `research_change`, `research_strategy`, `research_interpretation`, and
`research_checkpoint`; lifecycle actions are stored in the canonical State
`lifecycle_actions` collection.
There is no generic `memory.commit` operation that could bypass domain
validation.

Every Research Turn follows:

```text
TRIGGER -> ORIENT -> PLAN -> PREPARE -> EXECUTE
        -> WAIT/RECONCILE -> INTERPRET -> ADVANCE -> CHECKPOINT
```

Before ending, the Agent must call `research_checkpoint` with one of the
current dispositions: `continue_required`, `waiting_external`, `deferred`,
`blocked`, `terminal`, or `user_input_required`. `continue_required` records an
explicit next-turn action chosen by the Agent. Lifecycle actions are stored in
the canonical State `lifecycle_actions` collection.
`research.liveness` is a bounded diagnostic projection, not a persisted next
step or a turn-closing command. An active Node with no valid disposition yields
`decision_needed`. When the focused scope has an active StrategyPlan, the
projection also sets `execution_ready=true`, so the Host may admit the planned
prepare/execute work in the same turn; the Agent must still record a checkpoint
before ending that turn. Without `execution_ready`, the Host admits only reads,
planning, interpretation, and checkpoint repair. The Harness may issue a
bounded follow-up asking the Agent to read context and checkpoint a disposition,
but it never chooses a scientific method or creates a Finding. `next_run` is an
operational wake-up, not a new research instruction. A prepared request has not
started execution. Started, running, or unknown Attempts can hold their scope
in `waiting_external`; a completed Job still requires explicit collection,
interpretation, and current acceptance before research can finish.

The liveness response exposes canonical `continue_required` records only.

Public tools use one contract and a Harness-bound workspace context. The
legacy `root` field is accepted only as an equality assertion. Tool contracts
declare authority, side effects, replay/idempotency, lifecycle phase, and
output schema; Research Writes go through Research State ChangeSets, execution tools
produce Attempts/Artifacts, and advisory tools never own scientific state.
The server-extension loader rejects tools that do not provide the complete
`label`, `description`, parameter schema, executable, and four-field Harness
metadata contract before they enter a Worker.

Tool factories and transport adapters have separate responsibilities. The
`create*Tool()` functions define domain behavior and may throw typed failures;
they are not themselves a transcript or transport boundary. The package-owned
server extension composes those factories, and the Native `pi-session-worker`
applies the Harness adapter at the Worker boundary. Successful results receive
the `tspi-tool-result/1` envelope. Failures are converted to a normal result
with `tspi-tool-error/1`; the Native `after_tool` hook then sets `isError: true`,
so the durable transcript preserves both the machine-readable failure and the
model-visible error status. Direct factory tests may call the domain tool
without this adapter; production Harness traffic enters through the Native
server-extension boundary.

### NodeGate And ClaimGate

NodeGate and ClaimGate are Gate records distinguished by their `scope`:

```text
Gate.criteria    = versioned completion or evaluation criteria
Gate.evaluations = one or more evaluation records
scope            = node | claim
```

A NodeGate checks whether a bounded Node can close. A ClaimGate checks whether
the current Findings support or contradict a Claim. Gates record evaluations,
but never silently update a Node or Claim; the Root Agent submits that
interpretation through a Map ChangeSet.

## ChangeSets And Browser Clients

Native server tools, Host commands, and slash commands all submit the same
small ChangeSet envelope to the Research State filesystem boundary port. The Research State
validates operation fields, references, optimistic revision, and graph
invariants before atomically committing the canonical context/liveness
projections and manifest revision. A failed ChangeSet leaves the previous
revision untouched.

TS Web reads the canonical map through `components/ts-web/`; it does not own Pi
sessions or submit prompts. It is a browser client of the same map, not a
separate protocol or scientific state store. Browser control is a separate,
explicitly started loopback adapter (`apps/app-server/tspi-browser-gateway.mjs`)
attached to the Host's existing session; it uses request IDs for idempotency
and sequence cursors for reconnects. TS Phone uses the same underlying
services through TSPi Link.

## TSPi Link

```text
TS Phone -- outbound WSS --> TSPi Link Relay <-- outbound WSS -- TSPi Host
                                                        |
                                                  Unix socket / RPC
                                                        |
                              Pi App Server -> SessionWorker + durable Harness
                                  ^                    ^             ^
                                  |                    |             |
                         native Pi TUI              Phone         Monitor
```

Both network-facing legs use `/v1/link` with the `tspi-link.v1` WebSocket
subprotocol and distinct bearer credentials. A short-lived Host enrollment
code creates the Host credential; a short-lived Phone pairing code creates a
revocable device credential. The Relay maps an authorized device to its Host
and forwards framed `tspi-host/1` NDJSON bytes without parsing them. This is
deliberately a TSPi transport contract, not Pi's experimental remote protocol.

The TSPi Link Relay owns no workspace, session, transcript, tool, or compute state.
The Host owns routing and access control; the Pi Harness worker remains the
owner of its session, transcript, model, and tools. WSS protects both network
legs, but Link 1 does not provide application-level end-to-end encryption; the
Relay must run on trusted infrastructure.

The Link Relay is installed and upgraded by the standalone `install-link-relay.sh`
installer on its public or private network host. The local TSPi installer only
enrolls its Host against an existing Link Relay and never installs a local Phone
broker or transport service.

## TSPi Lifecycle

The `ts-app-server-tspi.service` unit invokes TSPi's Host entrypoint and creates
installation state at `var/state/host/`, including one stable server ID,
the Host socket, SQLite sessions, receipts, scheduler leases, and Monitor health.
The Pi App Server is the runtime owner below that Host. Its SQLite durable sessions
are stored in `var/state/pi/sessions/<workspace-id>/<session-id>/`; `meta.json`
keeps `workspace_id`, `session_id`, and `cwd` together so routing uses identity
while the agent loop still executes in the workspace directory. Workspace
`.pi/sessions` files are outside the supported Native runtime boundary.

`ResearchAgent --workspace <name>` bootstraps the selected workspace, asks Host for
`session/list` plus `session/create`/`session/resume`, and then execs Pi's
official `ExperimentalClientTui` against the returned local connection
descriptor. The remote TUI owns completion, rendering, input handling, and its
supported slash commands, including workspace-scoped `/resume`; standalone Pi
session commands are not exposed by this client. Phone uses Host RPC and
Monitor submits a durable `next_run` entry to the same lane. Disconnecting a
client does not stop the worker or its current turn. `TSPI_HOST_BACKEND` must be
`harness`; the retired ordinary-Pi backend is rejected.

The first client launch initializes a missing workspace through the same
validated bootstrap. The Host never creates an unnamed workspace; a client must
request a valid direct-child name explicitly.

The launcher validates installation ownership, package identity, workspace
path safety, and runtime configuration before executing Node/Pi. A second Host
for the same installation fails on the Host Root lock rather than creating a
parallel history.

The selected release, worker facet, server-extension allowlist, and pinned Pi
source are deterministic and package-validated. Presentation facets remain
client-side and optional; they cannot change the worker's tool inventory.

## Agent execution

The Native Pi Harness runs the research agent. Scientific computation uses Job
Runtime, and the same agent interprets collected evidence. TSPi has no separate
Compute/Review agent implementation, task aggregator or parallel session store.

## Deterministic Tool Plane

`artifact_derive` records a derivation descriptor; it does not dispatch analysis
or produce scientific outputs. Scientific scripts live in Domain Skills and run
through generic Job Runtime. Register the actual outputs with their input digests
and provenance. Registered validators are listed in extension manifests and are
invoked with `job_start`; no analysis capability catalog is required.

The chemical extension provides molecular preparation, Gaussian/xTB/CF22D runners,
report building and registered validators. The finite mapped Diels–Alder path adds
RDKit candidate seeds, Gaussian QST2/Freq and bidirectional IRC preparation, plus
separate mapping, forming-bond mode and endpoint-connectivity checks. These checks
require bound collected outputs; they do not establish exhaustive mechanism discovery
or guarantee actual Gaussian convergence. See the candidate-generation Skill for
supported structures, output formats and validation limits.
Other installed scientific commands can use generic Jobs after their actual input
and output contracts are verified. No execution result implicitly updates a Claim.

TS Web renders the canonical `ResearchMap` document directly. Findings and Gate
evaluations are ordinary map records, so the browser never reconstructs
scientific state from backend logs or a second registry. It does not infer the
next action from tool exit codes. See [ADR 0003](adr/0003-minimal-research-state-and-gates.md).

Public tools validate input paths, normalize artifacts and return machine-readable
errors. Skills select scientific commands and parse their outputs. Generic Jobs
use the same public tools for local and remote environments:

```text
job_start     -> stage inputs, submit
job_status    -> inspect execution and bounded output
job_collect   -> collect declared outputs and issue result receipts
job_cancel    -> request cancellation
job_reconcile -> resolve uncertain execution state
```

Scientific parsing and interpretation remain explicit Skill work. The Job's
`platform` selects an installation environment. The Research State workspace
is always canonical, while a remote directory is only a
temporary execution mirror. Local runs stage inputs under `runs/jobs/<job_id>/` and
collect outputs back into the same workspace paths, so TS Web needs no remote
filesystem access. Local workers are launched in an independent transient
systemd service when available, so restarting the App Server Host does not
kill an in-flight local calculation; environments without a user systemd
manager use the process-group fallback and should avoid restarting the parent
service during a calculation.

## Monitor and automation lifecycle

The Monitor is an App Server control-plane sibling worker. It is not part of a
Root session and it is not a daemon owned by an individual workspace. One
installation Host runs one worker, which can scan the direct-child workspaces
under its configured workspace root. Each workspace persists its own monitor
records under `operations/monitors/<monitor_id>/`:

```text
binding.json        # Job/Attempt/session binding, digest, and latest observation
events/<event_id>.json
deliveries/<event_id>.json
```

The binding, event, and delivery envelopes are versioned by
`ts-job-monitor/1`, `ts-job-monitor-event/1`, and `ts-job-monitor-delivery/1`.
A tick reads Job Runtime status and records the corresponding Attempt observation.
Terminal execution states and `unknown` can produce wake events; collection and
scientific interpretation remain explicit work. An unchanged observation does not
create another event, except for a newly exceeded configured queue-wait threshold.

The worker normally delivers an event to the bound session with `next_run`,
which does not interrupt an active Root turn. Its request id is
`job-wake:<event_id>`. A missing session or an App Server restart leaves the
delivery pending and allows a later worker pass to retry it. Root must reread
`research_read`, inspect the Job with `job_status`, collect its evidence with
`job_collect`, and decide which interpretations or Research State changes are
justified. Monitor records execution observations; it does not collect outputs,
update scientific conclusions, or send user notifications.

Research liveness is a diagnostic projection separate from Monitor
observations. The turn boundary persists the Agent's disposition through
`research_checkpoint`. It is the canonical checkpoint; lifecycle actions are
managed by canonical ChangeSet operations. ChangeSet audit fields belong to
`research_change`. At a run boundary the
Host follows the checkpoint result and the bounded continuation policy; it
never chooses the next method. Thus research can continue after collection even
when Monitor has no new status event, while a blocked or deferred study remains
quiet and auditable.

Host `monitor/event` notifications are live only. Host primes its event cursor
on startup instead of replaying historical files after a restart; Phone clients
refresh `monitor/status` and the durable delivery outbox when reconnecting.

`job.toml` keeps local and remote compute environments in one catalog, with
backend bindings under each environment; only remote environments add
SSH/Torque fields. `job_probe` checks a selected platform; this does not prove
that a scientific method is ready. Method-specific checks use the configured
commands and Skill helpers.

## Run Journals And Result Delivery

Each operation writes an immutable request/result pair and a content-addressed
artifact record. Remote jobs are identified by scheduler and job ID; retries
are explicit and never overwrite prior evidence. Pi transcript events
are separate from the scientific operation journal.

## Contract Locations

- Host and client adapter entrypoints: `apps/app-server/*.mjs`.
- Installation/runtime launcher: `ResearchAgent`, `apps/agent-cli/tspi_launcher.py`, and
  `packages/tspi-bootstrap/tspi_bootstrap/launcher.py`.
- Python namespaces: `packages/tspi-foundation/`,
  `packages/tspi-runtime/`, `packages/tspi-bootstrap/`,
  `packages/research-state/`, `packages/research-memory/`,
  `packages/job-runtime/`, `packages/artifact-store/`, and chemistry under
  `extensions/chemical/skills/`.
- Skills and extension manifests: `extensions/core/skills/`, domain extension manifests, `package.json`, and
  `apps/app-server/server-tools/extensions.json`.
- TS Web contracts: `contracts/ts-web/`.
- Monitor contracts: `contracts/tspi-monitor/1/`.
- Host lifecycle and Native Harness integration tests: `tests/integration/test_pi_app_server_launcher.py`,
  `tests/node/native/tspi-host.test.mjs`, `tests/node/native/worker-research-flow.test.mjs`, and
  `tests/node/native/pi-session-control.test.mjs`.


## Sourced requirements and current acceptance

`research-requirements/1` adds user deliverables without replacing scientific Claims.
Host records actual Pi user submissions; Monitor and State continuation messages
are internal inputs. Installed versioned acceptance profiles declare finite checks.
A requirement binds its source quote, constraints, inputs and contributing Nodes;
receipt-based assessments derive satisfaction. Source coverage remains an Agent
judgment, so preserving a source is not proof of complete natural-language extraction.

Node Gate changes cannot weaken a requirement's original checks. Stage Nodes may
complete before it, and fulfilled analysis can leave a Claim inconclusive. Stops
preserve unmet work with actual cancellation or scoped failure evidence. New Attempts
expire old stopping decisions. A completed delivery retains its historical consumed
requirement versions while current evidence can become stale and prevent new success.

`dependency_evaluation` is shared by admission, liveness and completion, with
`completed` or `finished` conditions. Delivery declares consumed requirements,
Artifacts or predecessor Nodes. Email preparation binds its event and consumption
to State; send rechecks that basis. Existing sent/unknown receipts remain idempotent.

Prepared Job references (`pN`) and Artifact references (`aN`) are exact persistent
workspace records. Transaction journal v2 recovers only pending commits after a
one-time history migration. Stop all old workspace writers before upgrading; do
not directly downgrade an upgraded workspace. See
[the migration notes](MANAGED_REFERENCES_AND_TRANSACTION_RECOVERY.zh-CN.md).

During a State bridge outage only native local read/system_prompt diagnostics can
bypass unavailable admission; effects still require current State. A failed initial
user-source write prevents starting that input. A later failed yield check preserves
the diagnostic answer without manufacturing a checkpoint or continuation.


The removed parallel framework and state implementations are recorded in
[ADR 0010](adr/0010-retire-parallel-runtimes.md). Release checks reject their
reintroduction. Current State workspace data and existing Job receipts retain
their existing contracts; retired import facades have no compatibility shim.
