# ResearchMap Design Notes

[English](RESEARCH_MAP_DESIGN.md) | [简体中文](RESEARCH_MAP_DESIGN.zh-CN.md)

This document records the current, deliberately small research model. It is
not a second protocol or a compatibility plan.

## Canonical State

One project owns one ResearchMap. `ResearchMap` is a typed aggregate
containing `ResearchPhase`, `ResearchClaim`, `ResearchNode`, `Finding`, and
`Gate` records. `FactFinding` and `IssueFinding` are specializations of the
same `Finding` structure. `NodeGate` and `ClaimGate` are specializations of
the same `Gate` structure. Reverse indexes and graph dependencies are stored
in the map and checked by the model. The canonical runtime document is
`research_map/context.json`, selected by `workspace_manifest.json`; retired
JSON/SQLite files are diagnostic inputs only and are never Research State authority.

```text
ResearchClaim -> ResearchNode -> Finding
       ^               |          |
       |               +-------- Gate
       +---------------------- ClaimGate / NodeGate
```

`ResearchPhase` is optional grouping and navigation; it does not own a second
state machine. A Node has an explicit `state` (`planned`, `active`, `paused`,
`blocked`, or `closed`) and a closed outcome. A Claim has an independent
status. A Node can close with `completed` only when every attached NodeGate has
a latest `pass` evaluation.

## Research State Boundary

The Research State filesystem boundary is the only mutation authority. Callers submit
one ChangeSet with an expected revision and ordered operations. The Research State
validates the operation catalog, references, reverse indexes, cycles, and state
transitions, then atomically commits the context, liveness, memory projection,
checkpoint, and manifest revision. A failed request leaves the previous
revision untouched.

The shared command surface is:

```text
research.map        complete map
research.summary    progress and focus
research.context    bounded turn context for the Root Agent
research.liveness   lifecycle diagnosis from map and runtime records
research.detail     one map object
research.locate     text search over map objects
research.validate   validate the map
research.operations operation catalog
research.decisions  bounded strategy/review/interpretation/checkpoint history
research.evidence   Attempt/Artifact/EvidenceLink metadata
research.storage    canonical filesystem storage status
research.strategy   record or review strategy
research.interpretation interpret an Attempt
research.checkpoint record a research disposition
research.change     apply one ChangeSet
```

The Host uses the read-only `research.monitor_assess` command to check a Monitor event against
the bound workspace, session, Attempt, and current research state before Host admission. It
does not persist a Pi input receipt or a turn audit.

The Agent-facing Research State port, Pi tools, slash commands, and Root Agent use this
command surface. Monitor assessment is an internal Host call, not an Agent tool. `research.context`
and `research.liveness` are bounded read models;
they do not become a second ResearchMap or a second lifecycle authority.
`research.context` and `research.liveness` are bounded projections. Liveness is
diagnostic and does not persist a next step. `research.checkpoint` records a disposition;
lifecycle actions are canonical ResearchMap records managed through `research.change`.
The liveness response exposes the read-only `continue_required` field.
`research.decisions` and `research.evidence` read bounded metadata without
loading raw files. `/research` is a presentation spelling of the command
service, not another API. TS Web reads the map snapshot through the ResearchMap
provider. `/compute` queries the unified local/remote environment catalog.

## Execution And Findings

Skills describe procedures and capabilities. Backends implement scientific
software or executors. A Compute Environment is a named `local` or `remote`
execution environment with Backend bindings. Platform configuration supplies
remote transport and scheduler details. One `compute.toml` holds local and
remote environment entries in the same catalog. Calculation Attempts and
Artifacts remain Node-owned operational records. Their manifests and typed
EvidenceLinks are registered as bounded metadata; raw files remain in the
workspace-owned artifact directories. A parser or analysis may produce transient candidate output, but only
an explicit ChangeSet creates a `FactFinding` or `IssueFinding` in the map.
Tool success never changes a Claim or closes a Node.

## Clients And Reports

The filesystem context has a canonical map-shaped projection consumed directly
by TS Web, Root Agent, and reports. Clients may filter or group records for
display, but they do not create a second scientific state model or registry.
Operational run records are shown separately from the map. Gates record
criteria and evaluation history; they do not silently update their target.

## Harness Workflow and Monitor Admission

The Root Agent is the only scientific decision-maker. It reads bounded context, selects and
executes actions through registered Skills and Capabilities, interprets evidence, and may
record a disposition with `research_checkpoint`: `continue_required`, `waiting_external`,
`deferred`, `blocked`, `terminal`, or `user_input_required`. This command records research
state; it is not a generic turn start/end protocol. Liveness is derived from the map and
runtime records. After a run yields, the Host may request a bounded follow-up when an active
scope still lacks a disposition. It cannot select a scientific method or write a Finding for
the Agent.

Ordinary input, Monitor wakes, and recovery enter through the current Pi submission and Worker
path. Before admitting a Monitor wake, Host calls the read-only `research.monitor_assess` with
the event and bound session. Research State verifies workspace/session ownership and compares
the event with current Attempt, interpretation, collection, and disposition state. Pi
submission is the durable input authority, and Host repeats this assessment before first model
consumption. A prepared but unsubmitted Attempt remains a local decision point and does not
justify waiting for a Monitor event.

## Delivery Checklist

- keep the canonical context/liveness/memory projections, Evidence/Decision
  metadata, and Node-owned execution directories as research workspace state;
  raw payloads remain in their artifact stores;
- add new map behavior as a model and ChangeSet operation, with focused tests;
- update the Research State operation catalog and focused tests for every new map behavior;
- update `packages/tspi-runtime/tspi_runtime/command_catalog.json` or
  `packages/agent-runtime/host-api/tools.mjs`; slash commands and host
  adapters consume those definitions directly;
- keep local and remote compute behavior behind the one `compute.toml` environment
  catalog;
- keep `ResearchMap` as the only scientific state model; do not introduce
  parallel scientific stores or aliases.
- cover Monitor event binding and revalidation at the Pi consumption boundary in the current
  Host/Worker tests; do not add a parallel Research State turn protocol.
