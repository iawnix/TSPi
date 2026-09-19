# ResearchMap Design Notes

[English](PLAN_HYPOTHESIS_PROOF_LOOP.md) | [简体中文](PLAN_HYPOTHESIS_PROOF_LOOP.zh-CN.md)

This document records the current, deliberately small research model. It is
not a second protocol or a compatibility plan.

## Canonical State

One project owns one `research_map.json`. `ResearchMap` is a typed aggregate
containing `ResearchPhase`, `ResearchClaim`, `ResearchNode`, `Finding`, and
`Gate` records. `FactFinding` and `IssueFinding` are specializations of the
same `Finding` structure. `NodeGate` and `ClaimGate` are specializations of
the same `Gate` structure. Reverse indexes and graph dependencies are stored
in the map and checked by the model.

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
on a detached copy, then atomically writes the map and appends a transaction
receipt. A failed request leaves the previous revision untouched.

The shared command surface is:

```text
research.map        complete map
research.summary    progress and focus
research.detail     one map object
research.locate     text search over map objects
research.validate   validate the map
research.operations operation catalog
research.change     apply one ChangeSet
```

The CLI, Pi tools, slash commands, Root Agent, and TS Web use these same
commands. `/research` is a presentation spelling of the command service, not
another API. `/compute` queries the same unified local/remote environment
catalog through `compute.environments` and `compute.environment`.

## Execution And Findings

Skills describe procedures and capabilities. Backends implement software.
Platforms describe local, container, or HPC execution environments. One
`compute.toml` contains both local and remote environments; an environment's `kind`
selects transport details. Calculation Attempts and Artifacts remain
Node-owned operational records. A parser or analysis may produce transient
candidate output, but only an explicit ChangeSet creates a `FactFinding` or
`IssueFinding` in the map. Tool success never changes a Claim or closes a Node.

## Clients And Reports

`ResearchMap.to_dict()` is the canonical serialized document consumed directly
by TS Web, Root Agent, and reports. Clients may filter or group records for
display, but they do not create a second scientific state model or registry.
Operational run records are shown separately from the map. Gates record
criteria and evaluation history; they do not silently update their target.

## Delivery Checklist

- keep only `research_map.json`, `transactions.jsonl`, and Node-owned execution
  directories as research workspace state;
- add new map behavior as a model and ChangeSet operation, with focused tests;
- update the Kernel operation catalog and focused tests for every new map behavior;
- update `packages/ts-agent-kernel/ts_agent/command_catalog.json` or `packages/ts-agent-runtime/host-api/tools.mjs`; slash
  commands and host adapters consume those definitions directly;
- keep local and remote compute behavior behind the one `compute.toml` environment
  catalog;
- remove obsolete registry, proof, acceptance, and projection templates rather
  than adding aliases.
