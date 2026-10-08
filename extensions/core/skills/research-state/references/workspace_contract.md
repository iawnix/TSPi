# Research Workspace Contract

## Contents

- [Canonical State](#canonical-state)
- [Bootstrap And Identity](#bootstrap-and-identity)
- [Write Boundary](#write-boundary)
- [Relationships](#relationships)
- [Runtime Records](#runtime-records)

## Canonical State

Every research workspace is bound by one immutable-identity
`workspace_manifest.json`. Its contract is
`schema_version=research_state_workspace_2`, `workspace_mode=research`, an
absolute `workspace_root`, a stable `workspace_id`, and `state` equal to
`admission_pending` or `ready`. The manifest binds admission and routing; the
ResearchMap revision is stored in the context and liveness projections.
The canonical workspace ID grammar is
`^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$`; the same value is used by Host routes,
Research State requests, local run records, and remote calculation intents.

The manifest also fixes the authority split and directory surface. Research
workspaces must contain `profile_id=research_workspace_1`,
`memory_profile=session`, `memory_scope=session`,
`research_state_scope=workspace`, `execution_profile=audited`, and
`research_state={initialized:true, admission_required:<state is not ready>,
revision:<non-negative integer>}`. The required directories are exactly
`inputs`, `artifacts`, `runs`, `logs`, `research_map`, `memory`, `lifecycle`,
`checkpoints`, `nodes`, `evidence`, `monitor`, and `environments`. Light
workspaces use the same schema with `profile_id=light_workspace_1`,
`research_state_scope=none`, `execution_profile=bounded`,
`research_state={initialized:false, admission_required:false, revision:null}`,
and directories `inputs`, `artifacts`, `runs`, `logs`, `scratch`, and
`sessions`. Host, App Server, Research State, and Monitor readers reject a manifest
that omits or changes these fields; they do not infer defaults from a path.

The scientific read model is `research_map/context.json` and must use
`schema_version=research_map_context_2`. It contains the complete collection
surface, even when a collection is empty. The required array collections are:

```text
phases, claims, nodes, findings, gates, claim_relations,
attempts, artifacts, evidence_links, lifecycle_actions,
strategy_plans, strategy_reviews, attempt_interpretations
```

`focus` is required and has array fields `claim_ids` and `node_ids`. The
context `workspace_id` and `workspace_mode=research` must match the manifest.

Lifecycle admission is `lifecycle/liveness.json` with
`schema_version=research_liveness_2`; its `workspace_id`, `state` and
`revision` must agree with context. The bounded runtime projection is
`memory/index.json` with `schema_version=research_memory_index_1`. It carries
`context_revision`, lifecycle and focus metadata plus explicitly registered
entries. It is a metadata/lifecycle projection, never a second ResearchMap or
scientific authority. Context and liveness are written with the memory
projection atomically by the Research State filesystem boundary. There is no
JSON/SQLite fallback authority.

The Agent Core `memory_profile` and `memory_scope` remain `session` in
research mode. Durable scientific state belongs to the Research State and is
selected by `research_state_scope=workspace`; do not treat the memory
projection as conversation memory or write scientific facts through the Core
memory port.

Raw execution payloads live under the Node/Attempt and Artifact stores. The
Research State context stores typed Claims, Nodes, Findings, Gates, relations, focus,
Attempt records, Artifact manifests, EvidenceLinks, decisions, and revision.
Artifacts are referenced by their logical `art_<sha256>` IDs; absolute or
remote paths never become scientific object references.

Execution records are rooted at `nodes/<node_id>/` and remain operational
records referenced by the canonical context.

## Bootstrap And Identity

Only the Host may initialize and admit a research workspace. Initialization
creates the manifest and canonical context/liveness/memory documents in
`admission_pending`; Host admission changes all related documents to the
admitted/ready state. Every reader validates the manifest, physical files,
workspace root, mode, ID, lifecycle state, and revision before returning data.
Partial, symlinked, legacy, or mixed layouts fail closed and are not migrated
implicitly.

## Write Boundary

The normal flow is:

```text
research_read -> Root interpretation -> research_change
```

All Research State writes require the Host-bound identity:

```json
{"principal":"root_agent","authority":"kernel_write"}
```

This identity is attached by the Host to the internal Research State request; the
public `research_change` tool payload does not include these authority fields.

`research_change` loads the current canonical context under the workspace lock,
checks `expected_revision`, applies the ordered ChangeSet to a detached copy,
validates the complete post-state, and atomically commits context, liveness,
memory projection, and manifest revision. A rejected request changes nothing.
Do not edit any canonical document by hand.

## Relationships

- A Phase may list its Nodes; a Node may belong to one Phase or remain ungrouped.
- A Node may cite Claims and earlier Node dependencies.
- A Finding belongs to one producing Node and may cite Claims and source refs.
- A Gate targets exactly one Node or Claim and is indexed by that target.
- Node dependencies and Claim relations are acyclic.
- Focus contains existing Claim and Node IDs only.

Node state and Claim status are independent. Closing a Node requires an outcome;
closing it as `completed` also requires every attached NodeGate to have a latest
`pass` evaluation. An open IssueFinding is visible progress information, not an
implicit veto unless a Gate criterion says so.

## Runtime Records

Calculation intents, Attempts, run journals, scheduler receipts, parser output,
Review runs, rendered files, report packages, notifications, and UI state are
operational records. Attempt records, Artifact manifests, and EvidenceLinks are
registered as bounded metadata in the Evidence Registry; their raw payloads
remain in Node-owned directories or an external store. A Finding or Gate may
cite only registered, validated evidence references after Root verifies the
primary Artifact. A successful execution never changes a Claim or Node
automatically.
