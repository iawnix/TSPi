# Architecture

The normative unified Research Harness lifecycle is defined in [ADR 0006](adr/0006-unified-research-harness-lifecycle.md).

[English](ARCHITECTURE.md) | [简体中文](ARCHITECTURE.zh-CN.md)

TSPi packages scientific skills and runtime adapters on top of Pi. One
installation Host serves all direct-child workspaces, while each active
workspace has one pinned Pi `SessionWorker`/`AgentHarness` lane. The terminal,
Phone, and Monitor are clients of that lane; none owns a second agent loop or
replacement UI.

## Component Responsibilities

- `apps/app-server/` contains the `tspi-host/1` control plane, the installation
  Pi App Server owner, native remote-client launcher, Monitor worker, browser
  adapter, and history migration tools. The pinned Pi worker loads TSPi's
  worker facet (tools, skills, hooks, policy, and system prompt).
- `services/tspi-link-relay/` owns TSPi Link enrollment, pairing, device
  authorization, and opaque frame forwarding. It has no workspace, session, or
  research APIs and does not decode Host RPC.
- `packages/ts-agent-kernel/ts_agent/` owns the `ResearchMap`, reference
  integrity, validation, and transactions. Its
  `compute_run` control plane uses one lifecycle for local subprocesses and remote
  scheduler jobs; the configured remote adapter supplies transport and
  readiness operations. Rendering, reporting, and email remain
  Skill/Plugin tools.
- `extensions/pi/` contains only the small Native TUI presentation helpers
  required by the client facet. Direct ExtensionAPI adapters and their public
  entrypoints have been removed; they are not selected by the launcher or
  loaded by the Native Pi Worker.
  `extensions/server/` is the sole package-owned tool entry. The App Server
  loads only the allowlisted, digest-verified entries in
  `extensions/server/extensions.json`; the worker also loads package skills,
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

Pi's App Server owns the session directory, transcript history, model state,
prompt loop, and worker lane. The Host owns routing, authentication,
idempotency receipts, scheduler leases, and client subscriptions. The native
Pi TUI, Phone, and Monitor address the same lane and therefore see the same
`read`, `write`, `bash`, and package tool inventory; transport is not an
authorization role.

## Scientific State Model

Each workspace has one canonical ResearchMap and one durable metadata backend:

```text
research.db                # SQLite authority for map and bounded metadata
research_map.json           # synchronized ResearchMap snapshot
workspace.json           # validated workspace identity and schema marker
nodes/<node_id>/          # Attempt and Artifact execution records
inputs/                   # workspace-relative imported input artifacts
transactions.jsonl       # append-only ChangeSet receipts
operations/               # turn, monitor, and execution receipts
```

`ResearchMap` is the canonical project object. It is not assembled as a
derived view from separate scientific registries. It contains `ResearchPhase`,
`ResearchClaim`, `ResearchNode`, typed `Finding` objects, and typed `Gate`
objects, together with their dependency, output, and target references.

Attempts and Artifacts are not scientific facts inside the ResearchMap. They
are produced by the Compute/Workspace runtime, while their stable identity,
digest, provenance, lineage, and evidence references are governed by the
Research Kernel's Evidence Registry. Raw files remain in the workspace or an
object store; the Kernel stores bounded Artifact Manifests and Evidence Links,
and never turns scheduler state or file contents into a Finding or Claim
conclusion by itself.

```text
Compute Runtime -> Attempt -> Artifact Manifest
                              |
                              +-> Evidence Link -> Claim/Finding/Gate
```

An Artifact is not a Finding. It is a verifiable data object; an Evidence Link
records whether it supports, contradicts, qualifies, or derives a scientific
object; and a Finding is the Root Agent's scientific statement based on that
evidence. Large logs, trajectories, and images stay out of the ResearchMap and
model context; Agents read bounded manifests, summaries, and on-demand
excerpts.

### ResearchMap And Research Kernel

`ResearchMap` is a typed research graph. `ResearchClaim` represents a scientific
statement, `ResearchNode` represents bounded work, and `ResearchPhase` is an
optional navigation grouping. Nodes produce a common `Finding` base type:
`FactFinding` records a confirmed fact and `IssueFinding` records a problem,
contradiction, or risk.

```text
ResearchClaim -> ResearchNode -> FactFinding / IssueFinding
       ^               |                  |
       |               +------ Gate <-----+
       +----------- ClaimGate / NodeGate
```

`ResearchKernel` loads, validates, commits, and persists the `ResearchMap`.
`ResearchMap.to_dict()` is canonical serialization for TS Web and Root Agent,
not a second scientific model. The Root Agent chooses questions, methods,
branches, and stopping conditions. Skills describe research procedures,
Capabilities describe callable operations, and Backends implement scientific
software or executors. A Compute Environment is a named `local` or `remote`
execution environment with Backend bindings; Platform configuration supplies
the transport and scheduler details for a remote environment. Tool success
never becomes a scientific conclusion by itself.

### Domain-Neutral Research Harness Lifecycle

The Research Harness is domain-neutral. Chemistry, reaction mechanisms, data
analysis, simulation, and other research domains use the same Claims, Nodes,
Findings, Gates, Attempts, and Artifacts. Domain-specific behavior belongs in
Skills, Capabilities, Backends, and Artifact schemas; it must not be encoded in
Host scheduling or Kernel liveness rules.

```text
Agent (only scientific decision-maker)
  -> bounded Research Context -> Research Kernel (canonical ResearchMap)
  -> Harness/Host (turn admission, authority, recovery, follow-up)
       +-> Monitor (external observation and next_run wake-up)
       +-> Compute/Workspace runtime (Attempts, Artifacts, environments)
```

Durable Research Memory remains in the workspace. Each turn gets a bounded
`research.context` read model containing the current focus and compact runtime
summaries; it is not a second scientific state and does not copy full history
or every Skill into model context. Each category has a fixed item limit and a
fixed text/reference limit and a truncation marker; arbitrary continuation
metadata and large reference lists are reduced to keys and bounded IDs. Full
records remain available through focused map/detail queries. Skill catalogs are
loaded when a worker is created and Skill bodies are cached for explicit
invocation; only names, descriptions, and locations are placed in the model's
default prompt. Capabilities and Compute
Environments are queried when selecting or launching a method.

The runtime boundary is explicit:

```text
Research Memory (durable records)
  -> ResearchMemoryService (one facade over the canonical store)
  -> ContextBuilder (bounded deterministic projection)
  -> ContextPack (ephemeral turn working set)
  -> Prompt (ContextPack plus tools, Skill metadata, and instructions)
```

`ResearchMemoryService` does not cache a second ResearchMap or persist a
ContextPack. `ContextPack.context_id` and provenance identify the source
revision so a Host can rebuild it after a change or retry. Semantic writes stay
on `research_change`, `research_strategy`, `research_interpretation`, and
`research_checkpoint`; new turns do not write through `research_continuation`,
which is retained only to read or migrate old required-action ledger records.
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
explicit next-turn action chosen by the Agent. The old `required` value is
accepted only while reading or migrating a `research_continuation` ledger and
is normalized to `continue_required`; it is not a second lifecycle state.
`research.liveness` is a bounded diagnostic projection, not a persisted next
step or a turn-closing command. An active Node with no valid disposition yields
`decision_needed`; the Harness may issue a bounded follow-up asking the Agent
to read context and checkpoint a disposition, but it never chooses a
scientific method or creates a Finding. `next_run` is an operational wake-up,
not a new research instruction. An Attempt in `prepared` state has only a
local, pre-submission binding and is therefore a decision point for the Agent,
not an external wait. Only submitted, queued, running, completed-but-unparsed,
or unknown Attempts hold a scope in `waiting_external` until the Host/Monitor
produces new evidence.

For transport compatibility, the liveness response may mirror the canonical
`continue_required` records under the read-only `required` field; that alias
does not make `required` a new lifecycle disposition.

Public tools use one contract and a Harness-bound workspace context. The
legacy `root` field is accepted only as an equality assertion. Tool contracts
declare authority, side effects, replay/idempotency, lifecycle phase, and
output schema; Research Writes go through Kernel ChangeSets, execution tools
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

`NodeGate` and `ClaimGate` specialize one `Gate` base class:

```text
Gate.criteria    = frozen completion or evaluation criteria
Gate.evaluations = one or more evaluation records
scope            = node | claim
```

A NodeGate checks whether a bounded Node can close. A ClaimGate checks whether
the current Findings support or contradict a Claim. Gates record evaluations,
but never silently update a Node or Claim; the Root Agent submits that
interpretation through a Map ChangeSet.

## ChangeSets And Browser Clients

Native server tools, Host commands, and slash commands all submit the same
small ChangeSet envelope to `ResearchKernel`. The kernel validates operation
fields, references, optimistic revision, and graph invariants before atomically
committing the active Research Memory backend and updating its JSON snapshot and
transaction receipt. A failed ChangeSet leaves the previous revision untouched.

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
                              Pi App Server -> SessionWorker + AgentHarness
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
installation state at `.pi/app-server-host/`, including one stable server ID,
the Host socket, format-4 sessions, receipts, scheduler leases, and Monitor health.
The Pi App Server is the runtime owner below that Host. Its format-4 sessions
are stored in `.pi/app-server-host/sessions/<encoded-cwd>/`; workspace
`.pi/sessions` files are outside the supported Native runtime boundary.

`TSPi --workspace <name>` bootstraps the selected workspace, asks Host for
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

## Isolated Agent Runtimes

Compute and Review agents run as bounded Pi subagents with explicit task and
result schemas. They receive only the context and tools declared by the App
Server package; skills remain top-level Pi capabilities.

## Deterministic Tool Plane

`analysis_run` dispatches 22 independent versioned analysis capabilities from an
on-demand catalog. Domain code lives in `analysis/`; Node-owned artifacts bind
inputs, digests and generated files. Selected facts enter the existing
`research_change` candidate path after replay validation. No capability schedules a
scientific successor or accepts a Claim. Chemical networks use stoichiometric
hyperedges and may contain cycles, independently of the ResearchNode DAG.

`execution_dispatch` writes Node-scoped pause/resume receipts outside canonical science.
A shared lock orders pauses against new analysis and submission guards. In-flight
jobs remain inspectable, collectable and cancellable. Reports and TS Web expose
these execution records separately from the canonical map. See [ADR 0002](adr/0002-independent-scientific-capabilities.md)
and the [operations guide](SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md).

TS Web renders the canonical `ResearchMap` document directly. Findings and Gate
evaluations are ordinary map records, so the browser never reconstructs
scientific state from backend logs or a second registry. It does not infer the
next action from tool exit codes. See [ADR 0003](adr/0003-minimal-research-kernel-and-gates.md).

Public tools validate input paths against the workspace root, normalize
artifacts, and return machine-readable errors. Scientific backends are
selected by capability and parse only their own output formats. `compute_run` uses
the same four public operations for local and remote environments:

```text
launch   -> prepare, submit
inspect  -> status, optional tail
finalize -> collect, parse
cancel   -> cancel
```

These right-hand actions are private child-runtime steps, not additional public
operations. For either `execution_target.kind=local` or `remote`, the Research
Kernel workspace is always canonical, while a remote directory is only a
temporary execution mirror. Local runs stage inputs under the Attempt's execution directory and
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
registration.json   # intent binding, digest, and optional session binding
state.json          # last semantic observation
events/<event_id>.json
deliveries/<event_id>.json
```

The registration, event, and delivery envelopes are versioned by
`ts-compute-monitor/1`, `ts-compute-monitor-event/1`, and
`ts-monitor-delivery/1`. A tick calls the Compute Kernel status API directly.
`completed` means that the program or scheduler ended; `parsed` means that
collection and parsing completed. `unknown` remains uncertainty, and an
unchanged observation does not create another event.

The worker normally delivers an event to the bound session with `next_run`,
which does not interrupt an active Root turn. Its request id is
`monitor:<event_id>`. A missing session or an App Server restart leaves the
delivery pending and allows a later worker pass to retry it. Root must reread
`research_read`, run `compute_run inspect`, and decide whether to collect, parse, or
write `ResearchMap` state. The Monitor never calls `finalize`, writes
`ResearchMap`, or makes a scientific decision.

Research liveness is a diagnostic projection separate from Monitor
observations. The turn boundary persists the Agent's disposition through
`research_checkpoint`. `research_continuation` remains only as a compatibility
ledger: it can list or resolve legacy records through `set`/`resolve` (the old
`set_*` spellings remain aliases), but new turns must use `checkpoint`.
Legacy `required` records are migrated to `continue_required`; they do not
define a second liveness state machine. ChangeSet audit fields belong to
`research_change`, not to this compatibility request. At a run boundary the
Host follows the checkpoint result and may add at most three bounded
follow-ups only for `decision_needed`; it never chooses the next method. Thus
a parsed calculation can continue even when Monitor has no new status event,
while a blocked or deferred study remains quiet and auditable.

Host `monitor/event` notifications are live only. Host primes its event cursor
on startup instead of replaying historical files after a restart; Phone clients
refresh `monitor/status` and the durable delivery outbox when reconnecting.

`compute.toml` keeps local and remote compute environments in one catalog, with
backend bindings under each environment; only remote environments add
SSH/Torque fields. The canonical `compute.environments` query exposes both
kinds of environment. Pi tools and the
`/compute` command use that query; scheduler diagnostics remain an
implementation detail of a remote environment rather than the name of the whole
environment API.

## Run Journals And Result Delivery

Each operation writes an immutable request/result pair and a content-addressed
artifact record. Remote jobs are identified by scheduler and job ID; retries
are explicit and never overwrite prior evidence. Pi transcript events
are separate from the scientific operation journal.

## Contract Locations

- Host and client adapter entrypoints: `apps/app-server/*.mjs`.
- Installation/runtime launcher: `TSPi`, `scripts/tspi_launcher.py`, and
  `packages/ts-agent-kernel/ts_agent/runtime/launcher.py`.
- Scientific contracts: `packages/ts-agent-kernel/ts_agent/**`.
- Skills and extension manifests: `skills/`, `package.json`, and
  `extensions/server/extensions.json`.
- TS Web contracts: `contracts/ts-web/`.
- Monitor contracts: `contracts/tspi-monitor/1/`.
- Host lifecycle and Native Harness integration tests: `tests/integration/test_pi_app_server_launcher.py`,
  `tests/node/native/tspi-host.test.mjs`, `tests/node/native/pi-native-worker.test.mjs`, and
  `tests/node/native/pi-session-control.test.mjs`.
