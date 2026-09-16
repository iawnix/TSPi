# Architecture

TSPi packages scientific skills and workflow extensions on top of Pi. One
installation Host serves all direct-child workspaces through one native Pi App
Server; there is no separate TS Phone broker or per-workspace service
requirement.

## Component Responsibilities

- `apps/app-server/` starts Pi's native App Server and session worker.
- `packages/ts-agent-kernel/ts_agent/` owns scientific contracts, workspace
  state, reference integrity, validation, and read-only projections. Calculation,
  remote execution, rendering, reporting, and email are Skill/Plugin tools; the
  Kernel does not own their execution lifecycles.
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

### Minimal Research Kernel

The scientific spine has four roles: `Claim` (a scientific statement),
`ResearchNode` (one bounded question and deliverable), `Observation` (verified
semantic evidence), and one scoped `GateSpec/GateResult` contract. A Hypothesis
is normally a proposed Claim (`status=proposed`); Attempts, Activities, Runs,
and raw artifacts remain execution records until the Root Agent promotes their
meaning to an Observation.

```text
Claim / Hypothesis -> ResearchNode -> Skill/Plugin runs
                                  -> Observation / Finding
                                  -> NodeGate -> Node outcome
                                  -> ClaimGate -> Claim interpretation
```

The Kernel owns IDs, references, digests, transactions, and projections. The
Root Agent chooses questions, methods, branches, and stopping conditions.
Skills and Plugins execute tools such as `ts_calc`, `ts_remote`, `ts_render`,
and `ts_email`. At the Agent boundary the Kernel is the guarded `ts_state` /
`ts_change` tool surface; it can manage workspace identity and Node artifact
roots, but it is not another agent runtime. Tool success never becomes a
scientific conclusion by itself.

### NodeGate And ClaimGate

These are two scopes of one contract, not two new state machines:

```text
GateSpec   = frozen completion or evaluation criteria
GateResult = one digest- and input-revision-bound evaluation
scope      = node | claim
```

A NodeGate checks whether a bounded Node can close: for example, its deliverable
is recorded, owned runs are terminal, and blocking Findings are handled. A
passing NodeGate only permits a terminal Node outcome; it does not support the
primary Claim. A ClaimGate evaluates whether declared evidence supports,
refutes, or cannot yet decide a Claim. It normally composes existing
`ProofSpec`, `ValidationResult`, and acceptance-profile records. A ClaimGate
result never silently updates Claim status or creates an Acceptance; the Root
Agent submits that interpretation through `ts_change`.

Gate production is explicit: the Root Agent selects intent and a profile;
Plugins advertise supported predicates and schemas; the Kernel expands the
profile, checks refs, binds the predicate registry, and freezes the GateSpec
before evaluation. Tools can provide evidence after that point, but cannot
silently change the criteria or verdict. The standalone
`gate_spec.schema.json` and `gate_result.schema.json` contracts are introduced
alongside explicit `freeze_gate` / `evaluate_gate` mutations. Those mutations
lazily create `gate_specs.json` and `gate_results.json`; old workspaces without
those files remain valid and continue to receive derived Gate projections.

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

`TSPi --host` creates the installation Host state at `.pi/app-server-host/`,
generates one stable server UUID, acquires the Host Root lock, and starts Pi's
native App Server. Its session directory is `.pi/app-server-host/sessions/`;
each session is created with a project cwd under `workspaces/`, enforced by
`TSPI_WORKSPACE_ROOT`. The workspace-directory service exposes only validated
direct-child workspaces containing a supported `workspace.json`.

`TSPi --workspace <name>` is the native TUI client. It connects to the Host and
passes `TSPI_SESSION_CWD` when creating a session, so the session worker keeps
the selected project's filesystem context. TS Phone uses the same service and
can switch projects without opening another Host connection. The old
`--app-server --workspace <name>` mode remains only as a compatibility path.

The launcher validates installation ownership, package identity, workspace
path safety, and runtime configuration before executing Node/Pi. A second Host
for the same installation fails on the Host Root lock rather than creating a
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

The Research Map reads a projection of Claims, Nodes, Observations, Gate
results, and dependency history. It shows how a question unfolded, which Node
produced tool runs and evidence, the Node outcome, and where a gate is blocked,
inconclusive, or stale; it does not
turn backend logs, Phase labels, or tool exit codes into scientific state or
infer the next action. See [ADR 0003](adr/0003-minimal-research-kernel-and-gates.md).

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
