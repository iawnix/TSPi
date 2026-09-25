# Research Workspace Contract

## Canonical State

Each research workspace owns `workspace.json`, one `research_map.json`,
`transactions.jsonl`, the workspace input directory `inputs/`, and Node-owned
directories under `nodes/<node_id>/`.
The document contains the complete `ResearchMap`: phases, claims, nodes,
findings, gates, Claim relations, focus, metadata, and revision. TS Web and
Root consume this document directly. Compute Attempts and Artifacts live in
Node-owned directories and can be cited by map objects.

## Bootstrap And Identity

Create the map through `workspace.engine.init_workspace()` or the Host
bootstrap that calls the same workspace initialization boundary. The map
identity and object IDs are workspace-local. The Kernel rejects malformed JSON,
duplicate IDs, unknown references, cycles, invalid enum values, and inconsistent
reverse indexes. Keep all artifact references logical and workspace-relative;
do not put absolute or remote paths in map objects.

The canonical scientific state file is `research_map.json`.
Bootstrap rejects an unsupported workspace without rewriting it.

## Write Boundary

The normal flow is:

```text
research.read -> Root interpretation -> research.change
```

`research.change` loads the current map under a lock, applies the ordered
ChangeSet to a detached copy, validates the complete post-state, increments the
revision, and replaces `research_map.json` atomically. A rejected request does
not change the prior revision. Do not edit the JSON or transaction log by hand.

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
operational records. They may be cited by a Finding through `source_refs` after
Root verifies the primary Artifact. A successful execution never changes a
Claim or Node automatically.
