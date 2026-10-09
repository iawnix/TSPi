# ResearchMap State Model

`ResearchMap` is the canonical, typed scientific state of one research project.
It contains research objects, execution evidence and user requirements. The
workspace contract owns its filesystem layout; the runtime command catalog and
operation schemas own exact fields and supported reads/writes. This reference
describes object roles and invariants rather than duplicating those contracts.
See [workspace ownership](workspace_contract.md) for storage boundaries and
[requirements](requirements.md) for user-delivery obligations.

## Objects

| Object | Role |
| --- | --- |
| `ResearchPhase` | Optional navigation group for related Nodes. |
| `ResearchClaim` | Scientific statement under investigation. |
| `ResearchNode` | Bounded question and deliverable with dependencies and evidence links. |
| `Requirement` | User-sourced deliverable and minimum acceptance; independent of the research plan. |
| `Finding` | Node output. Use `FactFinding` for a verified value and `IssueFinding` for a limitation, anomaly, conflict or open question. |
| `Gate` | Criteria and evaluations scoped to one Node or Claim; `NodeGate` and `ClaimGate` are typed scopes, not separate protocols. |

`Finding` is the common scientific conclusion structure. Execution evidence is
separate Research State metadata: `AttemptRecord`, `ArtifactManifest`, and
`EvidenceLink` form the Evidence Registry; raw payloads remain in Node-owned
directories or an external Artifact store. `GateEvaluation` stores a
verdict (`pass`, `fail`, `inconclusive`, `blocked`), timestamp, message,
evidence references, and the input revision.

## Status And Graph Rules

Claim status is one of `proposed`, `supported`, `contradicted`, `inconclusive`,
or `withdrawn`. Node state is one of `planned`, `active`, `paused`, `blocked`,
or `closed`. A closed Node has outcome `completed`, `inconclusive`, or
`stopped`; it cannot be reopened. A Node with dependencies is ready only after
all dependencies are closed with outcome `completed`. Closed/inconclusive or stopped dependencies do not admit execution. Node dependencies and Claim relations are
acyclic. Every NodeGate attached to a Node must have a latest `pass` evaluation
before that Node can be closed as `completed`. New Claims start as `proposed`;
`assess_claim` records reasons and evidence for scientific status updates.

Findings belong to exactly one producing Node and may cite Claims and source
references. Gates target exactly one Node or Claim. The map maintains reverse
indexes (`node_ids`, `finding_ids`, and `gate_ids`) and validates them on every
save.

## Reads And Writes

Agents use public `research_read` and `research_change` tools. The runtime
catalog is authoritative for current read modes and the operation catalog is
authoritative for write fields. Use `research_read mode=operations` before an
unfamiliar mutation and the requirements reference for requirement workflows.
Strategy, interpretation, checkpoint, Evidence Registry and map mutations use
typed Research State commands; do not create a generic memory write.

For `research_read mode=evidence`, optional selectors are `record_type` (`attempt`,
`artifact`, or `link`), `node_id`, `artifact_id`, `subject_id`, and `limit` (1--2048).
`record_type=link` selects `evidence_links`; it is not a second write protocol.

Lifecycle actions and checkpoints are State records managed through the public
Research State tools. The runtime operation catalog defines their current
operations and fields. Research State remains the only writer.

Do not edit canonical documents directly. A ChangeSet is validated against an
isolated copy, increments `revision` once, and atomically updates context,
liveness, memory, and manifest. The Host attaches the Root Agent `principal`
and `kernel_write` `authority` to every internal mutation request; an invalid
change leaves the prior revision untouched.
