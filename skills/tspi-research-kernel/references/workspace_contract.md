# Research Workspace Contract

## Canonical State

Every research workspace is bound by one immutable `workspace_manifest.json`.
The manifest records the workspace ID, absolute root, `workspace_mode=research`,
admission state, and Kernel revision. The scientific read model is
`research_map/context.json`; lifecycle admission is `lifecycle/liveness.json`;
the bounded memory projection is `memory/index.json`. These documents share the
same workspace ID and revision and are written atomically by the Filesystem
Research Kernel. There is no JSON/SQLite fallback authority.

Raw execution payloads live under the Node/Attempt and Artifact stores. The
Kernel context stores typed Claims, Nodes, Findings, Gates, relations, focus,
Attempt records, Artifact manifests, EvidenceLinks, decisions, and revision.
Artifacts are referenced by their logical `art_<sha256>` IDs; absolute or
remote paths never become scientific object references.

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

All Kernel writes require the Host-bound identity:

```json
{"principal":"root_agent","authority":"kernel_write"}
```

`research_change` loads the current canonical context under the workspace lock,
checks `expectedRevision`, applies the ordered ChangeSet to a detached copy,
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
