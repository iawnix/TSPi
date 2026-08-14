# Root Decision Protocol

## Normal Loop

1. Read the compact workspace report and its scientific and operational
   revisions.
2. Identify the exact unresolved Claim or missing fact.
3. Inspect only the relevant Node, artifact, or lineage delta.
4. Choose one bounded next act from scientific judgment.
5. Draft `ts-decision/3`, validate it, and apply it unchanged.
6. Run bounded operators, verify local artifacts, and register factual Evidence.
7. Evaluate declared Gates when their required facts are available.
8. Close the Node with explicit Claim updates or an inconclusive/blocked result.
9. Re-read state before selecting any continuation.

The Kernel may reject invalid references, stale revisions, inconsistent facts,
or a failed acceptance policy. It must not recommend a method or manufacture a
continuation.

## Previous Failed Exploration

When earlier work failed, read the failed Node and relevant attempt record. Use
`report_lineage_context(from_node, anchor_node)` only to compare an ancestor and
the Nodes attempted after it. Then independently decide whether to:

- retry the same immutable execution binding after a pre-effect failure;
- create a new calculation under the same scientific objective;
- open a child Node for a changed method or new question;
- append an alternative or revised Claim;
- ask for missing user constraints;
- stop.

Never rewrite or delete the failed Node to make the graph look successful.
Across independent repeated studies, preserve enough facts to distinguish a
reproduced scientific failure from a repeated infrastructure failure.

## Review

Review is advisory. Target one Claim; let the deterministic snapshot builder
collect its Claim ancestry, cited Evidence, Gate results, owner Nodes, and
allowlisted artifacts. After a successful result, record a concise Root
response with `ts_review_disposition`. Adopted advice still requires normal
workspace decisions and primary Evidence.

## Acceptance

Before accepted language:

1. identify the target Claim;
2. identify the named acceptance policy;
3. verify every cited Gate result is current, passing, and target-compatible;
4. state remaining limitations;
5. decide explicitly whether the complete study is finished.

A negative or inconclusive Gate result is a fact boundary, not an automatic
instruction to abandon or continue the research.
