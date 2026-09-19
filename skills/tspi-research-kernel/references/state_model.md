# ResearchMap State Model

`ResearchMap` is the canonical, typed state of one research project. The
serialized file is `research_map.json`; `ResearchMap.to_dict()` is the format
consumed by Root and TS Web. The Kernel loads, validates, and atomically saves
this same object.

## Objects

| Object | Role | Important fields |
| --- | --- | --- |
| `ResearchPhase` | optional navigation group for related Nodes | `title`, `objective`, `node_ids` |
| `ResearchClaim` | statement under investigation | `statement`, `status`, `predictions`, `falsifiers`, `node_ids`, `finding_ids`, `gate_ids` |
| `ResearchNode` | one bounded question and deliverable | `title`, `objective`, `phase_id`, `claim_ids`, `dependency_ids`, `state`, `outcome`, `finding_ids`, `gate_ids`, `artifact_refs`, `attempt_refs` |
| `Finding` | Node output | `node_id`, `statement`, `kind`, `status`, `claim_ids`, `source_refs` |
| `FactFinding` | verified value; `kind=fact` | `value`, `datatype`, `unit`, `provenance` |
| `IssueFinding` | limitation, anomaly, conflict, or open question; `kind=issue` | `severity`, `resolution` |
| `Gate` | criteria and evaluations for a Node or Claim | `scope`, `target_id`, `criteria`, `evaluations` |
| `NodeGate` / `ClaimGate` | typed Gate specializations | `scope=node` / `scope=claim` |

`Finding` is the common data structure. Use its specialized class rather than
inventing a parallel evidence record. `GateEvaluation` stores a
verdict (`pass`, `fail`, `inconclusive`, `blocked`), timestamp, message,
evidence references, and the input revision.

## Status And Graph Rules

Claim status is one of `proposed`, `supported`, `contradicted`, `inconclusive`,
or `withdrawn`. Node state is one of `planned`, `active`, `paused`, `blocked`,
or `closed`. A closed Node has outcome `completed`, `inconclusive`, or
`stopped`; it cannot be reopened. A Node with dependencies is ready only after
all dependencies are closed. Node dependencies and Claim relations are
acyclic. Every NodeGate attached to a Node must have a latest `pass` evaluation
before that Node can be closed as `completed`.

Findings belong to exactly one producing Node and may cite Claims and source
references. Gates target exactly one Node or Claim. The map maintains reverse
indexes (`node_ids`, `finding_ids`, and `gate_ids`) and validates them on every
save.

## Reads And Writes

Use these shared read commands:

```text
research.map          complete canonical map
research.summary      progress and focus
research.detail       one phase, claim, node, finding, or gate
research.locate       text search over map objects
research.validate     validate the map
research.operations   current ChangeSet operation catalog
```

The `ts_state` tool exposes the corresponding bounded modes (`map`, `summary`,
`detail`, `locate`, `validate`, `operations`) plus compute modes (`artifacts`,
`capabilities`, `runs`). Use `/research` for interactive reads. All mutations
use `research.change`, exposed as `ts_change` and implemented by the Kernel.

Do not edit `research_map.json` directly. A ChangeSet is validated against an
isolated copy, increments `revision` once, writes atomically, and appends a
small transaction receipt. An invalid change leaves the previous revision
untouched.
