# Decision Templates

These files are minimal `ts-decision/2` examples for the canonical research
node ontology. Replace every `${NAME}` placeholder with workspace-specific
values, then validate the rendered decision before applying it.

```bash
python "$TS_AGENT_SKILL_ROOT/scripts/ts_workspace.py" \
  validate_decision --root <workspace> --decision-file decision.json
```

The supported sequence is intentionally not a fixed pipeline:

1. Start and close the `n000` intake node.
2. Start and close a `mechanism` proposal node.
3. Add `candidate_search`, `validation`, `mechanism`, or `audit` nodes as the
   hypothesis and evidence require.
4. Register evidence with `update_evidence.json` before citing it in closure.

`end_program_node.json` is for candidate and validation nodes. It records only
program facts. Hypothesis status belongs to mechanism-node closure; acceptance
belongs to audit-node closure.

Every post-`n000` start carries explicit `branch_context`. Change its relation
and provenance only after inspecting the relevant historical node and branch
context. Scientific retries that change the method use
`attempt_kind=recalculation`, a `recalculation_ref`, and
`relation=recalculation_of`; transport retries remain calculation attempts
under the same node.

The templates show shape and ownership boundaries. They do not choose a
mechanism, method, branch, evidence verdict, or acceptance result.
