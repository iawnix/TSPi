# ResearchMap Change Templates

These snippets are examples for the current canonical `research.change`
operation envelope. Combine only the operations needed for one atomic
ChangeSet, replace the placeholders, and include a rationale plus optional
`expected_revision` and `basis_refs`.

The `type` names and fields match `ts_state mode=operations`. IDs are explicit
because the ResearchMap is a small project-local data structure; never reuse an
existing ID. These snippets are examples, not a required research sequence.
