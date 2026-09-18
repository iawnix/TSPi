# Pi Runtime Adapter

TSPi embeds the Research Kernel into Pi. Python modules are deterministic
services, not a second Agent runtime.

## Contents

- [Loaded Surface](#loaded-surface)
- [Root Conversation](#root-conversation)
- [Context](#context)
- [Review Isolation](#review-isolation)
- [Compute Isolation](#compute-isolation)
- [Result Delivery And Journals](#result-delivery-and-journals)
- [UI](#ui)
- [Package Sources](#package-sources)

## Loaded Surface

Normal startup registers nine Skills, five extensions, one theme, fourteen public
tools, and four slash commands. The orchestration Skill is the cross-cutting
contract; domain Skill bodies are loaded when the active question matches.
`ts_calc` and `ts_review` create isolated child sessions. `ts_analyze` runs locally
in the host and records an analysis artifact. All underlying compute actions, structure seed,
input import, Render, Report, remote inspection, workspace control, Review
disposition, and notification remain deterministic host calls.

## Root Conversation

A Pi conversation may contain many user/assistant turns. The workspace is the
scientific source of truth; the conversation is not. Completing a ResearchNode
does not inject a new message by itself. The current tool result is visible in
the active turn; later turns should read a frontier or delta projection.

The control extension adds a short active-workspace and package-source reminder
before each Root run. It does not replace Pi's system prompt or inject the full
workspace.

## Context

Use graph modes `frontier`, `claim`, `node`, `subgraph`, `finding`,
`proof`, or `delta`. Use `ts_state mode=artifacts` for artifact discovery and
`mode=capabilities capabilityKind=compute|analysis|proof|gate` for capability catalogs. Every bounded graph
projection reports its scientific/operational revisions and omitted counts.
For analysis details, add `query=<capability>@<version>`; the default index omits schemas.
The validation catalog stays compact; query one exact `templateId` and
`templateVersion` to retrieve its parameters and Observation selectors.

## Review Isolation

The Review host builds one Claim-centered snapshot and a compact
`ts-agent-task/2`. The child has:

- no parent transcript;
- no Root Skill or package extensions;
- no direct filesystem, shell, network, compute, or workspace mutation;
- no recursive delegation;
- exactly one `ts_review_result` tool;
- when the task selects artifacts, one batch-only `ts_review_artifact_read`
  tool bound to their logical IDs and immutable digests.

The initial provider packet contains no artifact paths or contents. The child
may submit directly or read up to six semantic sections in one bounded batch.
The host then forces the named result tool, validates `ts-agent-result/1`
locally, checks task/scope/citation identity, and permits one same-session
structural repair. Artifact citations are accepted only for IDs actually read.
Provider-side strict function mode is deliberately not required. Provider
HTTP/stream errors must remain provider errors.

Review remains advisory. The Root records a separate disposition and uses the
normal Decision pipeline for any scientific change.

## Compute Isolation

The Compute host resolves one Node-owned intent before starting the child and
builds a compact `ts-agent-task/2`. The child has no parent transcript, Skill,
package extension, built-in tool, filesystem, shell, arbitrary argument, or
recursive delegation. It receives only the zero-argument tools for one plan:

```text
launch   prepare -> submit
inspect  status -> optional tail
finalize collect -> parse
cancel   cancel
```

Every action is single-use and bound to the exact intent digest. A failed first
step stops a dependent plan. An ambiguous submit or cancel stops without retry.
`ts_compute_result` accepts only summary and limitations; the host derives the
structured outcome and provenance from typed action receipts. No Compute result
changes canonical science until Root verifies artifacts and applies a Decision.

## Result Delivery And Journals

The immediate tool return delivers the result into the current Root turn.
Compute/Review tasks and Review-bound inputs are durable; normal terminal
handling writes actions, result, and run summary. A process crash can leave a
pending/unknown journal, and no background replay exists.

Deterministic tools keep activity journals plus their domain records. Compute
guards/receipts, not UI state, are authoritative for remote recovery.

## UI

The foreground working message summarizes whether Root is thinking or running
Compute, Review, or deterministic tools without gaining authority. It is
transient and contains no run IDs or audit paths.
`/runs` is a paginated read-only Compute/Review browser: its list
uses canonical `sub_n` run IDs, while details put outcome and error before scope,
actions, artifacts, and audit metadata. Pi's normal expand key expands/collapses
tool details globally; the history browser paginates its own list.

## Package Sources

Registered schemas, live catalogs, the Skill family, and references are the
research interface. Implementation source, tests, and maintainer docs are not
runtime examples. The package-source guard routes attempted source inspection
back to public contracts; it is not a general filesystem sandbox.
