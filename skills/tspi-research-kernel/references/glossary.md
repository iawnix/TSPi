# Public Glossary

[Chinese](glossary.zh-CN.md)

Use these names in prompts, tool requests, findings, and reports.

| Term | Meaning |
| --- | --- |
| Root Agent | Chooses research questions, methods, branches, interpretation, and stopping. |
| Research Kernel | Validates and atomically persists one project `ResearchMap`; it does not run scientific software. |
| ResearchMap | Canonical typed aggregate for a project, serialized as `research_map.json`. |
| ResearchPhase | Navigation group for related research Nodes. It has no independent lifecycle. |
| ResearchClaim | Statement under investigation with predictions, falsifiers, and a status. |
| ResearchNode | One bounded question and deliverable, with dependencies, state, outcome, and links to Claims, Findings, Gates, Attempts, and Artifacts. |
| Finding | A Node output stored in the map. Use `FactFinding` for a verified value and `IssueFinding` for a limitation, anomaly, conflict, or open question. |
| Gate | Criteria and evaluations attached to one Node or Claim. `NodeGate` and `ClaimGate` are typed scopes, not separate protocols. |
| Artifact | Logical reference to an input, output, or analysis file owned by a Node. |
| Attempt | One bounded calculation or execution record owned by a Node. Retries remain Attempts; a changed question starts a new Node. |
| Compute environment | Named local or remote execution environment with bound Backends. Query it with `compute_environment` or `/compute`. |
| Claim relation | Directed relation between Claims, such as support, conflict, or dependency. |
| ChangeSet | Explicit list of map operations submitted through `research_change`. The Kernel validates and commits it as one revision. |
| Review | Isolated advisory assessment. Root records the disposition in the map. |
| Skill | Method guidance for an agent. It may choose tools and interpret outputs but does not own canonical research state. |
| Backend | Scientific software or executor used by a calculation. |
| Platform | Transport and scheduler details used by a remote Compute environment. |

Use exact values from the live map and operation catalog. Keep raw execution
output, parser diagnostics, scheduler state, and Review advice separate until
Root verifies and records the relevant fact or issue through `research_change`.
