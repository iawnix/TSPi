# ResearchMap State Model

`ResearchMap` is the canonical, typed scientific state of one research project.
The Research State filesystem boundary persists it in `research_map/context.json` with
`schema_version=research_map_context_2`. A valid context always has array
collections `phases`, `claims`, `nodes`, `findings`, `gates`, `claim_relations`,
`attempts`, `artifacts`, `evidence_links`, `lifecycle_actions`, `strategy_plans`,
`strategy_reviews`, `attempt_interpretations`, `claim_assessments`, and `claim_revisions`; its `focus.claim_ids` and
`focus.node_ids` are arrays. Lifecycle is projected to
`lifecycle/liveness.json` (`research_liveness_2`); `workspace_manifest.json`
binds identity, mode, root, and admission. Retired SQLite and
`research_map.json` files are rejected and are not runtime authorities.

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

The Research State command catalog uses these internal read IDs:

```text
research.map          complete canonical map
research.summary      progress and focus
research.detail       one phase, claim, node, finding, or gate
research.locate       text search over map objects
research.validate     validate the map
research.operations   current ChangeSet operation catalog
research.context      bounded turn context
research.liveness     lifecycle diagnosis
research.decisions   bounded strategy/interpretation/checkpoint history
research.evidence    Attempt/Artifact/EvidenceLink metadata
research.storage     canonical Research State filesystem boundary documents and revision
```

Agents call the public `research_read` tool with the corresponding bounded
`mode` (`map`, `summary`, `detail`, `locate`, `validate`, `operations`,
`context`, `liveness`, `decisions`, `evidence`, or `storage`). The tool also
exposes compute modes
(`evidence`, `storage`). Use `/research` for interactive reads.
Strategy, interpretation, checkpoint, Evidence Registry, and map mutations use
their typed Research State commands; do not create a generic memory write.

For `research_read mode=evidence`, optional selectors are `record_type` (`attempt`,
`artifact`, or `link`), `node_id`, `artifact_id`, `subject_id`, and `limit` (1--2048).
`record_type=link` selects `evidence_links`; it is not a second write protocol.

Lifecycle actions are State records managed through `research.change`; the
`research_checkpoint` command is the turn checkpoint. Use the canonical
`set_lifecycle_action` and `resolve_lifecycle_action` operations with explicit
scope, target, action, status, reason, and request identity. The Research State remains
the only writer.

Do not edit canonical documents directly. A ChangeSet is validated against an
isolated copy, increments `revision` once, and atomically updates context,
liveness, memory, and manifest. The Host attaches the Root Agent `principal`
and `kernel_write` `authority` to every internal mutation request; an invalid
change leaves the prior revision untouched.
