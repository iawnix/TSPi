# Storage and recovery

The workspace manifest uses `research_workspace/2`. Original requests, authored changes and execution observations have distinct sources. The unified Python namespace is `research_agent.research`; there is no parallel state or global-progress protocol.

Research Nodes have stable IDs and work directories under `research/nodes/<node_id>/`. Immutable Results preserve the Node revision and actual evidence they refer to. Records retain changes; indexes, reverse links, workspace/Node Markdown and bounded retrieval are rebuildable views. Change relationships without moving Node directories.

`operations/` holds runtime-owned dispatch, collection and delivery receipts. `artifacts/<id>/payload` and its manifest own fixed file bytes and provenance. Mutable Node work files must be registered before they become published materials. Pi owns session history; Memory survives a session and does not replace it.

Use public tools for managed research data, native file tools for work files. Transactions publish coherent updates; request receipts recover retries. An uncertain dispatch must be reconciled using its original identity, not repeated with a new Job. An uncertain email remains a delivery problem; rewriting Memory cannot resend it.

Old workspaces are unsupported and are not migrated or rewritten. Create a new workspace and explicitly import useful materials. Exact reference errors require inspecting the current object, not fabricating an ID or fallback location.
