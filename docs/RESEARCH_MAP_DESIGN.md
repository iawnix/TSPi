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
in the map and checked by the model. `research_map.json` is the synchronized map
snapshot; after SQLite bootstrap, `research.db` is the authoritative Kernel
backend for the snapshot, decision records, and evidence metadata.

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

## Kernel Boundary

`ResearchKernel` is the only mutation authority. Callers submit one ChangeSet
with an expected revision and ordered operations. The kernel validates the
operation catalog, references, reverse indexes, cycles, and state transitions
on a detached copy, then atomically commits the active backend, updates the JSON
snapshot, and appends a transaction receipt. A failed request leaves the
previous revision untouched.

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
research.storage    active backend and bootstrap status
research.turn       unified turn admission/checkpoint boundary
research.strategy   record or review strategy
research.interpretation interpret an Attempt
research.checkpoint close a turn with a disposition
research.continuation compatibility required-action ledger
research.change     apply one ChangeSet
```

The Kernel API, Pi tools, slash commands, and Root Agent use these same
commands. `research.context` and `research.liveness` are bounded read models;
they do not become a second ResearchMap or a second lifecycle authority.
`research.context` and `research.liveness` are bounded projections. Liveness is
diagnostic and does not persist a next step. The `research.checkpoint` command
is the primary turn boundary; `research.continuation` is retained only for
compatibility and migration of older required-action records.
The liveness response may expose a read-only `required` field alias for older
transports; new callers should use `continue_required`.
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
EvidenceLinks are registered as bounded metadata; raw files remain outside
SQLite. A parser or analysis may produce transient candidate output, but only
an explicit ChangeSet creates a `FactFinding` or `IssueFinding` in the map.
Tool success never changes a Claim or closes a Node.

## Clients And Reports

`ResearchMap.to_dict()` is the canonical serialized document consumed directly
by TS Web, Root Agent, and reports. Clients may filter or group records for
display, but they do not create a second scientific state model or registry.
Operational run records are shown separately from the map. Gates record
criteria and evaluation history; they do not silently update their target.

## Research Harness Turn Boundary

The Root Agent is the only scientific decision-maker. A turn reads bounded
context, selects and executes a bounded action through registered Skills and
Capabilities, interprets the resulting evidence, and calls `research_checkpoint`
with one disposition before ending: `continue_required`, `waiting_external`,
`deferred`, `blocked`, `terminal`, or `user_input_required`. A pre-submission
`prepared` Attempt is still a local decision point; it does not justify waiting
for a Monitor event. The Harness may issue a bounded follow-up when liveness
reports `decision_needed`, but it does not select the next scientific method or
write a Finding.

## Delivery Checklist

- keep the map snapshot, active Kernel backend, transaction receipts,
  Evidence/Decision metadata, and Node-owned execution directories as research
  workspace state; raw payloads remain outside the metadata database;
- add new map behavior as a model and ChangeSet operation, with focused tests;
- update the Kernel operation catalog and focused tests for every new map behavior;
- update `packages/ts-agent-kernel/ts_agent/command_catalog.json` or
  `packages/ts-agent-runtime/host-api/tools.mjs`; slash commands and host
  adapters consume those definitions directly;
- keep local and remote compute behavior behind the one `compute.toml` environment
  catalog;
- keep `ResearchMap` as the only scientific state model; do not introduce
  parallel scientific stores or aliases.
- keep `tests/node/native/tspi-research-turn-e2e.test.mjs` as the domain-neutral
  acceptance trace for Agent -> Kernel -> Host -> Monitor -> Agent progress;
  domain-specific workflows must pass this lifecycle contract before adding
  scientific policy.
