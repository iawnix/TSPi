# Architecture

TSPi packages scientific skills and workflow extensions on top of Pi. A
workspace is served by one native Pi App Server; there is no shared TS Phone
Host.

## Component Responsibilities

- `apps/app-server/` starts Pi's native App Server and session worker.
- `packages/ts-agent-kernel/ts_agent/` owns scientific contracts, workspace
  state, validation, remote execution, rendering, and reports.
- `extensions/` contains optional standalone Pi workflow extensions. The native
  App Server does not inject them; its Worker exposes the equivalent guarded
  TSPi tools directly.
- `components/ts-web/` is an optional read-only browser projection.
- TS Phone is an independent Flutter client that connects through Pi Radius.

The App Server owns session directory, transcript history, model state, prompt
operations, and the workspace Root lock. The local TUI and TS Phone connect to
that same owner. Native Workers load the package's model-visible skills and
their native system prompt; extension manifests are not silently treated as
active prompt contributors.

## Scientific State Model

Each workspace has canonical files:

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
```

Phases group a research objective; nodes are executable or evidentiary units
within a phase. A node can reference artifacts and validation results without
changing the phase's lifecycle. The kernel validates all files before a
transaction commits.

## Decision Transaction

Workflow extensions emit one typed decision at a time. The workspace engine
validates the decision, checks references and optimistic revision, writes the
canonical record atomically, and appends a bounded operational journal. A
failed transaction leaves the previous revision untouched.

## Validation Engine

Validation templates and acceptance profiles live under
`packages/ts-agent-kernel/ts_agent/validation/`. Predicates are deterministic,
results record their input digest and template identity, and an acceptance can
reference only validated observations and findings.

## Context Compiler

The orchestration skill compiles a bounded context from canonical workspace
state, recent operations, and selected artifacts. It never invents a second
state store and never rewrites unsupported records during bootstrap.

## Read-Only Web Projection

TS Web reads the workspace files through `components/ts-web/`. It does not own
Pi sessions or submit prompts. Its optional systemd unit is independent from
the App Server instance.

## TSPi Lifecycle

`TSPi --app-server --workspace <name>` creates the workspace when necessary,
generates a stable UUID at `.pi/app-server/server-id`, acquires the Root lock,
and starts Pi's native App Server. Its session directory is
`.pi/app-server/sessions/`; the private local socket is under the user runtime
directory. `TSPi --workspace <name>` is the native TUI client and attaches to
that socket.

The launcher validates installation ownership, package identity, workspace
path safety, and runtime configuration before executing Node/Pi. A second App
Server for the same workspace fails on the Root lock rather than creating a
parallel history.

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

`ts_manage` writes Node-scoped pause/resume receipts outside canonical science.
A shared lock orders pauses against new analysis and submission guards. In-flight
jobs remain inspectable, collectable and cancellable. Reports and TS Web expose
these states through read-only projections. See [ADR 0002](adr/0002-independent-scientific-capabilities.md)
and the [operations guide](SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md).

Public tools validate input paths against the workspace root, normalize
artifacts, and return machine-readable errors. Scientific backends are
selected by capability and parse only their own output formats.

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
- Skills and extension manifests: `skills/` and `package.json`.
- TS Web contracts: `contracts/ts-web/`.
- App Server lifecycle tests: `tests/test_pi_app_server_launcher.py` and
  `tests/pi-app-server.test.mjs`.
