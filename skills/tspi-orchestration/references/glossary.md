# Public Glossary

[English](glossary.md) | [简体中文](glossary.zh-CN.md)

Use these names for records and responsibilities. Scientific questions, methods,
tags, relation labels, and validation dimensions use open scientific vocabulary.

| Term | Meaning and owner |
| --- | --- |
| Root Agent | Chooses research questions, methods, branches, interpretation, and stopping. |
| Research Kernel | Validates and commits canonical scientific state through `ts_change`. |
| ResearchPhase | A title and objective grouping related research questions for navigation. |
| ResearchNode (Node) | One research question or decision episode, with dependencies, Claim scope, and an outcome. |
| Claim | A scientific statement with assumptions, falsifiers, status, and cited records. |
| ClaimRelation | A recorded scientific relationship between Claims, such as dependency, conflict, or alternative. |
| Artifact | An identified input, output, or analysis file with a digest and provenance. |
| Observation candidate | A parser-proposed value awaiting Root verification and explicit promotion. |
| Observation | An immutable semantic value bound to verified artifacts and provenance. |
| Finding | An explicit anomaly, limitation, conflict, or unresolved question. |
| Decision | One Root-authored atomic change, validated and committed by the Kernel. |
| ProofSpec | A versioned validation definition frozen before evaluation, with content and registry digests. |
| ValidationResult | A deterministic result over explicit, digest-bound Observations. Only `pass` satisfies a ProofSpec. |
| Acceptance record | An immutable snapshot of a Claim and its passing profile coverage. Currentness is derived separately. |
| Attempt | One Node-owned calculation execution. A retry or recalculation remains an Attempt; a new question starts a Node. |
| Compute | A child model carrying out a Host-bound calculation plan through its action tools. |
| Review | An independent, bounded advisory assessment of one Claim. Root records its disposition with `ts_reply`. |
| Reviewer role | A versioned specialty and budget within Review. The current role is `general`; its authority remains advisory. |

Use exact tool and field names from the live contracts. `frontier` and `delta`
are context read modes; `$alias` is local to a Decision draft. Revisions and
digests bind record versions. Root chooses subsequent research actions from
the question and available evidence.

Execution failures and scientific contradictions are different outcomes. Keep
scheduler, transfer, parser, provider, and contract diagnostics in their
operational records. Promote a scientific observation or limitation only after
verification through `ts_change`.
