# Public Glossary

[English](glossary.md) | [简体中文](glossary.zh-CN.md)

Use these names for records and responsibilities. Scientific questions, methods,
tags, relation labels, and validation dimensions use open scientific vocabulary.

| Term | Meaning and owner |
| --- | --- |
| Root Agent | Chooses research questions, methods, branches, interpretation, and stopping. |
| Research Kernel | The transaction boundary for research process and scientific state: it validates Claim, Node, Observation, Gate, and references, then commits through `ts_change`; it does not run calculation or email tools. |
| ResearchPhase | A title and objective grouping related research questions for navigation. |
| ResearchNode (Node) | One research question or decision episode, with dependencies, Claim scope, and an outcome. |
| Claim | A scientific statement with assumptions, falsifiability conditions, status, and cited records. A Hypothesis is normally a `status=proposed` Claim. |
| Evidence | The semantic role played by a verified Observation or declared Finding; raw execution output is not evidence until verified. |
| ClaimRelation | A recorded scientific relationship between Claims, such as dependency, conflict, or alternative. |
| Artifact | An identified input, output, or analysis file with a digest and provenance. |
| Observation candidate | A parser-proposed value awaiting Root verification and explicit promotion. |
| Observation | An immutable semantic value bound to verified artifacts and provenance. |
| Finding | An explicit anomaly, limitation, conflict, or unresolved question. |
| Decision | One Root-authored atomic change, validated and committed by the Kernel. |
| GateSpec | Frozen completion or evaluation criteria with a `node` or `claim` scope, versioned checks, and a digest. |
| GateResult | One evaluation of a GateSpec bound to an input revision, with verdict `pass`, `fail`, `inconclusive`, or `blocked`. |
| NodeGate | A `scope=node` Gate that determines whether a bounded research task can close; it does not establish a Claim. |
| ClaimGate | A `scope=claim` Gate that aggregates ProofSpec/ValidationResult and declared evidence for Claim interpretation. |
| ProofSpec | A versioned validation definition frozen before evaluation, with content and registry digests. |
| ValidationResult | A deterministic result over explicit, digest-bound Observations. Only `pass` satisfies a ProofSpec. |
| Acceptance record | An immutable snapshot of a Claim and its passing profile coverage. Currentness is derived separately. |
| Attempt | One Node-owned calculation execution. A retry or recalculation remains an Attempt; a new question starts a Node. |
| Compute | A child model carrying out a Host-bound calculation plan through its action tools. |
| Review | An independent, bounded advisory assessment of one Claim. Root records its disposition with `ts_reply`. |
| Reviewer role | A versioned specialty and budget within Review. The current role is `general`; its authority remains advisory. |
| Skill / Plugin | An execution extension that declares tools, input/output schemas, and check capabilities without owning canonical scientific state. |

Use exact tool and field names from the live contracts. `frontier` and `delta`
are context read modes; `$alias` is local to a Decision draft. Revisions and
digests bind record versions. Root chooses subsequent research actions from
the question and available evidence.

Here, a falsifier means a condition or observation that would disprove a Claim,
not fabrication. Execution failures and scientific contradictions are different outcomes. Keep
scheduler, transfer, parser, provider, and contract diagnostics in their
operational records. Promote a scientific observation or limitation only after
verification through `ts_change`.
