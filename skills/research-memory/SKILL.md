---
name: research-memory
description: Resume research through persistent problem Nodes, explicit relations, execution observations and immutable Results.
---

# Research Memory

Start from the injected workspace context or `research_read {}`. It preserves original user requirements and selects relevant Nodes, Results and execution facts within a budget. Omitted content is not absent or completed; use the returned references to inspect it. Scientific interpretation belongs to you and the domain Skill, not the execution receipt.

## Five small operations

- `research_read {}` restores the workspace overview; `{ref}` reads a returned Node, Result or record reference. Follow pagination to inspect a long object.
- `research_search {query}` finds research. Use the tool's declared filters and paging fields; copy exact returned references.
- `research_create {goal}` creates a persistent local problem. Optionally supply title, proposal, plan and initial explicit relations. A goal alone is enough.
- `research_update {node_id, note}` records a new observation or explanation. Optionally replace proposal, plan or progress, choose status (`open`, `paused`, `closed`), change explicit relations or set assessment_ref.
- `research_result {node_id, conclusion}` publishes an immutable, independently useful result. Optional observation, limitations, inputs, evidence_refs and files distinguish observations from interpretation. Set as_assessment only when this result should become the Node's current synthesis.

Framework identity, request deduplication, read basis and Node revisions are supplied by the adapter. Do not invent transaction fields. On a stale-read conflict, inspect the returned current Node, merge the scientific change, and retry through a new tool call. A Job update does not change the Node's authored revision. No global progress object or end-of-turn checkpoint exists.

For a large Node, inspect the specific field you intend to change:

```json
{"ref":"node_returned_by_create","field":"plan"}
```

Supported fields are goal, title, proposal, plan, progress, status, assessment_ref and relations. Follow next_offset for omitted content. All pages actually received for the same Node revision and field content together supply a replacement basis. Missing or unacknowledged pages do not authorize overwriting unseen text; if the revision changes, reread the field. The adapter acknowledges and combines read receipts.

## Continue a problem or start a branch

Keep parameter changes, different initial geometries and repeated attempts at the same question in one Node. Create another Node when the question or independently tracked branch changes. proposal states the current hypothesis or approach; goal states the question; plan states how to investigate. A hypothesis is optional for preparation or reporting work.

```json
{"goal":"Find a transition state connecting A and B","proposal":"A concerted path may exist"}
```

After inspecting a failed calculation, use its actual Node ID:

```json
{"node_id":"node_returned_by_create","note":"Geometry X did not converge; this does not refute the path. Try geometry Y.","plan":"Search from Y, then inspect frequency and IRC connectivity."}
```

## Express only necessary research relations

`add_relations` entries contain kind (`requires`, `part_of`, `alternative_to`), target and optional reason. Use `remove_relations` with returned relation IDs to withdraw a declaration. The framework stores the reverse query and history; do not update both endpoints yourself.

```json
{"node_id":"node_comparison","note":"Compare once the candidate has usable energy and connectivity evidence.","add_relations":[{"kind":"requires","target":"node_candidate","reason":"Need a comparable candidate result"}]}
```

The map can contain feedback and competing approaches. A dependency is research intent, not permission to call tools. Actual material usage and explicit result citations preserve their concrete versions. Merely reading or retrieving a result does not mean adopting it as evidence.

## Publish results without inventing success

A useful result can be negative or inconclusive. Job exit zero does not establish scientific validity; failure does not erase previous evidence. Publication does not close the Node. Closing a Node means stopping active work on that question, not proving its hypothesis.

```json
{"node_id":"node_candidate","conclusion":"This candidate's IRC does not connect the target product.","evidence_refs":["a7"],"limitations":"Only this candidate was checked; other geometries remain possible."}
```

For files use `files: [{name, purpose?, artifact_ref}]` referencing registered materials. Never cite a mutable work file as an immutable result. To correct a result, publish another with `supersedes` referencing the original. Ordinary new results do not overwrite the Node's assessment. Read a downstream review notice when an input result is corrected; it does not automatically change old inputs or rerun work.

Monitor events identify the Job and its research Node. Inspect or collect the execution, then record your interpretation here. No lifecycle repair prompt or mandatory disposition is needed to finish a turn.

See [storage and recovery](references/storage.md), [public tools](../research-workflow/references/public_contract.md), and [中文说明](SKILL.zh-CN.md).

## Subjects, checks and revisions

Use `subjects` to name immutable Artifact or Result references, for example `{"target":"a1","calculated":"a2"}`. Nodes describe intended subjects; Results record the subjects actually interpreted. Roles are explicit labels, not proof of identity. Domain tools compare structures; Memory never parses molecular graphs or certifies scientific truth.

Keep measured `observation`, authored `conclusion`, and exact `check_refs` separate. Checks may be failed or inconclusive; either may be cited in a Result. A check receipt records execution, parsing and scoped scientific checks separately.

To revise the current synthesis and progress together, publish with `supersedes`, `as_assessment:true` and `progress`. This operation is atomic: a stale read saves neither the Result nor the progress. Plain publication without progress retains its existing save-even-if-assessment-conflicts behavior. Read `subjects` before replacing them.

Result reads, current-assessment cards and generated Markdown expose review notices when the authored Node context changes or a cited Result is superseded. A report should be a Result with its files and exact input Results attached; those same notices apply to it. Notices request review, not retraction. Notes alone never rewrite progress. Historical Results and report bytes remain immutable.
