---
name: email
description: Prepare and send user-requested research email through configured SMTP or ClawEmail, with durable delivery receipts.
---

# Email delivery

An explicit request such as “email me the report when finished” authorizes that delivery once its recipient and contents are clear; it does not authorize unrelated sharing. Run this Skill's CLI through native bash with RESEARCH_AGENT_PYTHON; email delivery does not create a calculation Job.

1. Use scripts/email_cli.py check from this Skill directory to inspect installation configuration via RESEARCH_AGENT_NOTIFICATION_CONFIG before claiming settings are missing. The configured recipient owns addressing. Disclose only the diagnostic needed to resolve the issue, never secret values.
2. Build and inspect reports under reports/ or artifacts/. A draft contains stable notification_id, event, subject, summary and report_refs. Events are progress, report_ready, calculation_failed, calculation_ambiguous and study_completed. Describe actual results within user authorization.
3. prepare pins recipient, attachment digests and sizes without sending. Inspect the prepared request, then use send when authorized. The transport does not certify scientific completion; the Agent must state unfinished work honestly.
4. Preserve receipt_ref. sent means transport acceptance; already_sent returns the original receipt. Reconcile unknown/sending; never rotate IDs to retry an uncertain send. A record-registration failure requires recording recovery, not another email.

Research notes do not gate delivery. Progress updates do not invalidate prepared attachments; changed attachments or recipient require preparation again. Reusing notification_id with changed content is rejected. Read [delivery protocol](references/email_delivery.md).

```text
"$RESEARCH_AGENT_PYTHON" <this Skill directory>/scripts/email_cli.py check --root <workspace> --output reports/email/config-check.json
"$RESEARCH_AGENT_PYTHON" <this Skill directory>/scripts/email_cli.py prepare --root <workspace> --request-file reports/email/draft.json --output reports/email/prepared.json
"$RESEARCH_AGENT_PYTHON" <this Skill directory>/scripts/email_cli.py send --root <workspace> --request-file reports/email/prepared.json --output reports/email/result.json
```
