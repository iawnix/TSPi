---
name: tspi-email
description: Send configured email notifications for TSPi research events and reports, and track delivery receipts.
---

# TSPi Email Notifications

[Chinese version](SKILL.zh-CN.md)

Use this Skill for `ts_notify` and configured email delivery. Load
`tspi-orchestration` for operational, report, artifact, and state contracts.
Notifications communicate recorded research outcomes and link to their reports.
The installation may use the existing ClawEmail transport or the built-in SMTP
transport. SMTP presets currently cover 163 and QQ mailboxes.

## Operating Rules

- Use the recipient from the installation's notification configuration.
- Keep the provider, sender, and credentials in the installation configuration;
  notification requests must not select a provider or recipient.
- Select the event type and report attachments from the delivery contract.
- Record delivery receipts with the notification's operational history.
- Reuse the receipt for a known successful delivery. Inspect provider status
  before retrying an unknown delivery.
- SMTP uses TLS (implicit SSL or STARTTLS) and a provider-issued authorization
  code. Never place mailbox passwords or authorization codes in a workspace,
  request, report, or log.
- POP3 and IMAP are not used by this Skill; it sends notifications only.

Read [email_delivery.md](references/email_delivery.md) for the request shape, attachment rules,
receipt identity, and failure semantics.
