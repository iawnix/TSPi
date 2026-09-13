# Email Delivery Contract

`ts_notify` delivers a fixed event to the recipient owned by the TSPi
installation and records the delivery receipt.

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

Configure the recipient and credentials at installation level. The host writes
a digest-bound receipt and returns it for a repeated successful request.
For unknown delivery, inspect provider status before retrying. Delivery failures
are recorded with the notification's operational history.
