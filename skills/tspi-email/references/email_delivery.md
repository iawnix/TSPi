# Email Delivery Contract

`ts_notify` delivers a fixed event to the recipient owned by the TSPi
installation. It starts no child model and has no authority over canonical
scientific state.

When notifications are enabled, the request shape is:

```json
{
  "operation":"send",
  "event":"node_completed",
  "subject":"TS study update",
  "summary":"The bounded validation Node completed; connectivity remains open.",
  "reportRefs":["reports/final-study/final_report.md"]
}
```

Allowed events are `progress`, `node_completed`, `calculation_failed`,
`calculation_ambiguous`, and `study_completed`. Attachments must be existing
regular files listed by the exact `ts-report-package/4` manifest under
`reports/<packageName>/`. A Render file below `nodes/` must first be included by
logical artifact ID when building the report package.

The installation owns the recipient and credentials. Subject and summary text
cannot redirect delivery. The host writes a digest-bound receipt. Known success
is idempotent; ambiguous delivery is not automatically replayed. Notification
failure has no scientific effect and never changes a Claim, Node, Observation,
Finding, ProofSpec, ValidationResult, or acceptance record.
