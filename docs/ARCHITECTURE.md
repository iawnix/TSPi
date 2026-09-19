# Architecture

[English](ARCHITECTURE.md) | [简体中文](ARCHITECTURE.zh-CN.md)

TSPi packages scientific skills and runtime adapters on top of Pi. One
installation Host serves all direct-child workspaces through one native Pi App
Server; there is no separate TS Phone broker or per-workspace service
requirement.

## Component Responsibilities

- `apps/app-server/` starts Pi's native App Server and session worker.
- `packages/ts-agent-kernel/ts_agent/` owns the `ResearchMap`, reference
  integrity, validation, and transactions. Its
  `ts_calc` control plane uses one lifecycle for local subprocesses and remote
  scheduler jobs; the configured remote adapter supplies transport and
  readiness operations. Rendering, reporting, and email remain
  Skill/Plugin tools.
- `extensions/pi/` contains Pi research, compute, review, artifact, and UI
  adapters. `extensions/server/` contains the package-owned server tool entry.
  The App Server loads only the
  allowlisted, digest-verified entries in `extensions/server/extensions.json`;
  it never evaluates code supplied by a client.
- `components/ts-web/` is an optional read-only browser client that renders the
  serialized canonical `ResearchMap`. The optional
  `apps/app-server/pi-session-control-server.mjs` adapter exposes the same Host
  session to a browser over the versioned session-control contract; it attaches
  to an existing session and never owns a second Worker.
- TS Phone is an independent Flutter client that connects through Pi Radius.

The App Server owns session directory, transcript history, model state, prompt
operations, and the workspace Root lock. The local TUI and TS Phone connect to
that same owner and receive the same `read`, `write`, `bash`, and package tool
inventory; client transport is not an authorization role. Workers load the
package's model-visible skills, the native system prompt, and the selected
server extension inventory. The inventory is included in `sys_prompt`
provenance so a client can audit which tool set is active.

## Scientific State Model

Each workspace has one canonical research object:

```text
research_map.json
nodes/<node_id>/          # Attempt and Artifact execution records
inputs/                   # workspace-relative imported input artifacts
transactions.jsonl        # Kernel change history
```

`ResearchMap` is the canonical project object. It is not assembled as a
derived view from separate scientific registries. It contains `ResearchPhase`,
`ResearchClaim`, `ResearchNode`, typed `Finding` objects, and typed `Gate`
objects, together with their dependency, output, and target references.

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
Capabilities describe callable operations, Backends implement software, and
Platforms provide local, container, or HPC execution environments. Tool
success never becomes a scientific conclusion by itself.

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

Pi extensions, tools, the CLI, and slash commands all submit the same
small ChangeSet envelope to `ResearchKernel`. The kernel validates operation
fields, references, optimistic revision, and graph invariants before atomically
writing `research_map.json` and appending `transactions.jsonl`. A failed
ChangeSet leaves the previous revision untouched.

TS Web reads the canonical map through `components/ts-web/`; it does not own Pi
sessions or submit prompts. It is a browser client of the same map, not a
separate protocol or scientific state store. Browser control is a separate,
explicitly started loopback adapter (`TSPi --gateway`) backed by Pi's
`AgentController` and `Transcript`; it uses request IDs for idempotency and
sequence cursors for reconnects. TS Phone uses the same underlying services
through Pi Radius.

## TSPi Lifecycle

The `ts-app-server-tspi.service` unit invokes TSPi's internal Host entrypoint.
It creates the installation Host state at `.pi/app-server-host/`, generates one
stable server UUID, acquires the Host Root lock, and starts Pi's native App
Server. Its session directory is `.pi/app-server-host/sessions/`;
`.pi/app-server-host/workspace/` is only the Host's private Pi control cwd, not a
research project.
each session is created with a project cwd under the configured workspace root
(default `<install>/workspaces`), enforced by `TSPI_WORKSPACE_ROOT`. The
workspace-directory service exposes only validated direct-child workspaces
containing a supported `workspace.json`.

`TSPi --workspace <name>` is the native TUI client. It connects to the Host and
passes `TSPI_SESSION_CWD` when creating a session, so the session worker keeps
the selected project's filesystem context. TS Phone uses the same services to
list or create projects and to create or switch sessions without opening
another Host connection. The launcher starts the selected workspace through the
native App Server entrypoint; there is one current workspace launch path.

The first client launch initializes a missing workspace through the same
validated bootstrap. The Host never creates an unnamed workspace; a client must
request a valid direct-child name explicitly.

The launcher validates installation ownership, package identity, workspace
path safety, and runtime configuration before executing Node/Pi. A second Host
for the same installation fails on the Host Root lock rather than creating a
parallel history.

The systemd user unit sets `TSPI_SERVER_EXTENSIONS=tspi-server-tools` so the
release's server tool inventory is deterministic. A development host may set a
different allowlist, but every selected entry must remain inside the selected
Package release and match its recorded SHA-256 digest.

## Isolated Agent Runtimes

Compute and Review agents run as bounded Pi subagents with explicit task and
result schemas. They receive only the context and tools declared by the App
Server package; skills remain top-level Pi capabilities.

## Deterministic Tool Plane

`ts_analyze` dispatches 22 independent versioned analysis capabilities from an
on-demand catalog. Domain code lives in `analysis/`; Node-owned artifacts bind
inputs, digests and generated files. Selected facts enter the existing
`ts_change` candidate path after replay validation. No capability schedules a
scientific successor or accepts a Claim. Chemical networks use stoichiometric
hyperedges and may contain cycles, independently of the ResearchNode DAG.

`ts_dispatch` writes Node-scoped pause/resume receipts outside canonical science.
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
selected by capability and parse only their own output formats. `ts_calc` uses
one lifecycle (`prepare -> submit -> inspect -> collect -> parse`) for either
`execution_target.kind=local` or `remote`: the Research Kernel workspace is
always canonical, while a remote directory is only a temporary execution
mirror. Local runs stage inputs under the Attempt's execution directory and
collect outputs back into the same workspace paths, so TS Web needs no remote
filesystem access. Local workers are launched in an independent transient
systemd user service when available, so restarting the App Server Host does not
kill an in-flight local calculation; environments without a user systemd
manager use the process-group fallback and should avoid restarting the parent
service during a calculation.

`compute.toml` keeps local and remote software providers in one profile catalog;
only remote profiles add SSH/Torque fields. The canonical
`compute.environments` query exposes both kinds of profile. Pi tools and the
`/compute` command use that query; scheduler diagnostics remain an
implementation detail of a remote profile rather than the name of the whole
environment API.

## Run Journals And Result Delivery

Each operation writes an immutable request/result pair and a content-addressed
artifact record. Remote jobs are identified by scheduler and job ID; retries
are explicit and never overwrite prior evidence. App Server transcript events
are separate from the scientific operation journal.

## Contract Locations

- Pi App Server entrypoints: `apps/app-server/*.mjs`.
- Installation/runtime launcher: `TSPi`, `scripts/tspi_launcher.py`, and
  `packages/ts-agent-kernel/ts_agent/runtime/launcher.py`.
- Scientific contracts: `packages/ts-agent-kernel/ts_agent/**`.
- Skills and extension manifests: `skills/`, `package.json`, and
  `extensions/server/extensions.json`.
- TS Web contracts: `contracts/ts-web/`.
- App Server lifecycle tests: `tests/integration/test_pi_app_server_launcher.py` and
  `tests/node/native/pi-app-server.test.mjs`.
