# ADR 0007: Research Agent Framework Boundaries

- Status: accepted for the new framework
- Date: 2026-09-26
- Scope: new Research Agent Framework implementation

## Decision

The new framework is named **Research Agent Framework**. TSPi is not a
compatibility layer in this implementation; it is a future Chemistry Profile
that can be built on the framework.

The framework is split into these boundaries:

```text
Contracts
  -> Agent Core
  -> Research Kernel
  -> Native Compute Lifecycle (Python Kernel)
  -> App Server
  -> Runtime Adapter / Client Adapter
```

The Agent Core owns turns, model requests, tool invocation, context, retry,
and recovery. It does not own scientific state or a particular agent engine.

The Research Kernel is the only scientific state authority. It owns
ResearchMap, Research Memory, Claims, Nodes, Findings, Gates, Evidence Links,
and lifecycle decisions. It does not select or execute a scientific backend.

The Native Compute Lifecycle owns versioned capability descriptors, calculation
intents, Compute Attempts or light execution scopes, canonical Artifacts,
analysis results, and environment bindings. It never writes scientific Findings
or Claim status directly.

The App Server is the application composition root. It owns Host RPC,
workspace and session binding, permissions, receipts, recovery, Monitor, and
client adapters. It receives an `AgentRuntimePort` and does not import a
runtime implementation directly.

Pi is one Runtime Adapter. Pi imports, experimental source access, patch
verification, Pi SessionWorker, Pi AgentHarness, and Pi model integration are
confined to `agent-pi-adapter`. The framework does not invoke a
system-installed `pi` executable or consume ambient Pi configuration.

Protocol identifiers use snake_case. Examples are
`research_turn_request`, `research_turn_result`, `tool_result`,
`capability_descriptor`, and `artifact_manifest`. Dotted protocol identifiers
are not valid.

The new implementation does not preserve TSPi runtime compatibility paths,
old tool names, dotted protocol aliases, or old lifecycle entrypoints. A
migration may reuse scientific algorithms and data formats only when they are
explicitly reimplemented behind the new contracts.

## Runtime ports

The minimum language-neutral ports are:

- `AgentRuntimePort`: create, attach, submit, subscribe, interrupt, close;
- `ModelPort`: describe and stream model requests;
- `ContextPort`: build a bounded, disposable turn context from admitted inputs;
- `MemoryPort`: read and append session-scoped Agent memory. It is not a
  ResearchMap store; workspace-scoped research memory writes must go through
  `KernelPort`.
- `SessionPort`: create, list, attach, and enqueue session work;
- `KernelPort`: read context/liveness, apply changes, checkpoint, and execute
  a research turn boundary;
- `NativeComputeLifecycle`: describe capabilities, resolve environments,
  materialize intents, execute, inspect, finalize, cancel, and write canonical
  Artifacts.

All public request and result envelopes have versioned JSON schemas. TypeScript
and Python implementations consume the same schemas rather than importing
objects from one another.

## App Server composition

The App Server is wired as:

```text
App Server
  -> AgentRuntimePort
  -> KernelPort
  -> Native compute lifecycle (Python Kernel)
  -> MonitorPort
  -> Client adapters
```

The Host does not assemble JavaScript providers, gateways, or orchestrators. The Python Native registry owns descriptors, intent materialization, execution, and canonical Artifact records.

The Host exposes the Native `compute_run` lifecycle as the only calculation
entry point. Cancellation is scoped to the durable intent and controlled by
the Python Kernel; the Kernel remains the authority for terminal Attempt or
execution-scope state. Capability inventory and environment readiness are
read-only Native views, and there is no provider invocation API.

The default installation injects Pi Adapter. A Fake Runtime is required for
Core, Kernel, and App Server tests so that those tests do not require Pi,
network access, credentials, or a model provider.

## Scientific artifact boundary

Plain `read`, `write`, and `bash` operations may create scratch files, but they
do not create accepted scientific artifacts. Scientific inputs must pass
`artifact_create`, validation, and registration. A registered artifact may be
bound to a Compute Attempt and later promoted to Evidence by an explicit
Kernel change.

This allows simple systems such as water or methanol to be generated directly
when their structure validates, while keeping ambiguous complex structures in
the candidate and confirmation workflow.

## Installation boundary

Pi is an installation-owned, content-addressed runtime selected by a locked
source revision, dependency lock, and patch digest. Production startup rejects
source paths outside the selected installation runtime. The framework release
does not depend on a system Pi installation.

## Consequences

- New compute domains can be added through the Python Native registry and backend
  contract without changing Agent Core or Research Kernel.
- A future non-Pi Agent Runtime can reuse the App Server and Kernel contracts.
- Pi version changes are isolated to one adapter and its adapter tests.
- The initial implementation requires explicit contracts before broad directory
  movement or domain-specific feature work.

## Workspace modes

Workspace mode is selected by the Host during workspace initialization and is
immutable for the lifetime of that workspace. Sessions inherit the mode; a
model or tool cannot change it through a turn argument.

Workspace mode selects lifecycle and durable scientific-state policy; it does
not select a different Capability Registry. The manifest records two explicit
profiles:

| mode | memory profile | execution profile | scientific lifecycle |
| --- | --- | --- | --- |
| `light` | `session` | `bounded` | no ResearchMap, Claim, Node, Attempt, Evidence, or Monitor |
| `research` | `session` | `audited` | Kernel ResearchMap plus Attempt, Evidence, and Monitor |

The `light` profile starts with common inputs, artifacts, runs, logs, scratch,
and session directories. Native `compute_run` materializes an operational
execution scope under `nodes/<execution_scope>/attempts/` and writes canonical
workspace Artifacts. It never creates a ResearchMap Claim, Finding, Evidence,
Attempt, or Monitor.

The `research` profile creates the common directories plus ResearchMap,
memory, lifecycle, checkpoints, nodes, evidence, monitor, and environment
directories. It seeds an empty, valid Kernel state with lifecycle state
`admission_pending` and a genesis checkpoint. Host admission is a separate
`workspace_port_1` operation; the model must not create the first Phase or
Claim by issuing a normal change while the workspace is still orienting.

Changing scope requires a new workspace or an explicit Host-controlled fork.
Imported light artifacts remain candidates or inputs and do not become
Research Evidence automatically. The same Native `compute_run` lifecycle serves both profiles. A descriptor may
restrict execution to one or both modes; `light` uses an operational execution
scope while `research` adds Kernel Attempt/Evidence recording. Promotion from
light into research is an explicit Host/Kernel operation, never an implicit
inference from a successful process.

The mode also selects the turn contract: `light` sessions use
`agent_turn_request`/`agent_turn_result`, while `research` sessions use
`research_turn_request`/`research_turn_result`. This is a Host/Core policy
decision and is not inferred from a tool name.
