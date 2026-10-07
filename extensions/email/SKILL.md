---
name: email
description: Prepare and send user-requested research email through configured SMTP or ClawEmail, with durable delivery receipts.
---

# Research email

The listed SKILL.md is in `extensions/email`; its CLI is `extensions/email/scripts/email_cli.py` relative to the package root. Resolve the linked script against this SKILL.md directory.

Use this Skill for email tasks described above.

Use [scripts/email_cli.py](scripts/email_cli.py) through a **local** job_start. The installation owns notification configuration, credentials and recipient; inherit TS_NOTIFICATION_CONFIG or its configured installation path. Read [delivery rules](references/email_delivery.md) for request format and recovery.

Before asking for a recipient, run `"$TSPI_PYTHON" <listed-skill-directory>/scripts/email_cli.py check --root <workspace> --output <workspace>/reports/email-check.json` locally with the inherited TS_NOTIFICATION_CONFIG. This reads configuration and never sends. Reuse the configured recipient when enabled; ask only if configuration is missing, invalid, or the user requests another destination. A recipient need not be repeated in the latest message. Delivery problems must not block independent calculations.

1. Confirm the user's existing notification scope and completion condition. Reuse existing authorization; a plan or a Job completing alone does not authorize email.
2. Build the report and register its Artifact. Prepare a request with stable notification_id, event, subject, summary and report_refs. Run `email_cli.py prepare --root <workspace> --request-file <draft> --output <prepared.json>`; this never sends.
3. Run `email_cli.py send --root <workspace> --request-file <prepared.json> --output <receipt.json>` via job_start, with a bounded timeout. Declare the receipt output and collect it even on failure. Preserve the installation and workspace paths; never stage credentials remotely.
4. Read the delivery receipt. `sent` means transport acceptance, not inbox delivery or reading. `already_sent` reuses a prior receipt. `unknown` requires reconciliation, never blind retries. Use `status --receipt-ref <workspace-relative receipt> --output <status.json>` to inspect it.

Host/Monitor only wakes the Agent. This Skill owns notification preparation and delivery; no native notification tool or Provider registration is required. Failed email does not undo completed science. Notification IDs must not contain a Job ID, retry time or unrelated research revision.
