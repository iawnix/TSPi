---
name: tspi-email
description: Send configured email notifications for TSPi research events and reports, and track delivery receipts.
---

# TSPi Email Notifications

[Chinese version](SKILL.zh-CN.md)

Use this Skill for `ts_notify` and configured email delivery. Load
`tspi-orchestration` for operational, report, artifact, and state contracts.
Notifications communicate recorded research outcomes and link to their reports.

## Operating Rules

- Use the recipient from the installation's notification configuration.
- Select the event type and report attachments from the delivery contract.
- Record delivery receipts with the notification's operational history.
- Reuse the receipt for a known successful delivery. Inspect provider status
  before retrying an unknown delivery.
- Keep credentials and authentication URLs in private installation configuration;
  use research content and artifact references in messages and reports.

Read [email_delivery.md](references/email_delivery.md) for the request shape, attachment rules,
receipt identity, and failure semantics.
