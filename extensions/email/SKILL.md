---
name: email
description: Prepare and send user-requested research email through configured SMTP or ClawEmail, with durable delivery receipts.
---

# Research email

The listed SKILL.md is in `extensions/email`; its CLI is `extensions/email/scripts/email_cli.py` relative to the package root. Resolve the linked script against this SKILL.md directory.

Use this Skill for email tasks described above.

Use [scripts/email_cli.py](scripts/email_cli.py) through native **bash** on the local Host for all four commands: check, prepare, send and status. The installation owns notification configuration, credentials and recipient; inherit TS_NOTIFICATION_CONFIG or its configured installation path. Read [delivery rules](references/email_delivery.md) for request format and recovery.

Before asking for a recipient, run `"$TSPI_PYTHON" <listed-skill-directory>/scripts/email_cli.py check --root <workspace> --output <workspace>/reports/email-check.json` locally with the inherited TS_NOTIFICATION_CONFIG. This reads configuration and never sends. Reuse the configured recipient when enabled; ask only if configuration is missing, invalid, or the user requests another destination. Run this preflight before calculations if useful; it does not depend on result-delivery Node readiness. A recipient need not be repeated in the latest message. Delivery problems must not block independent calculations.

1. Confirm the user's existing notification scope and completion condition. Reuse existing authorization; a plan or a Job completing alone does not authorize email.
2. Build the report and register its Artifact. Bind the delivery Node to the requirements, material or predecessor Nodes being reported. Choose an event matching that scope; `study_completed` requires current acceptance of all tracked user requirements, while `node_completed` describes completed predecessors. Prepare a request with stable notification_id, node_id, event, subject, summary and report_refs. Run `email_cli.py prepare --root <workspace> --request-file <draft> --output <prepared.json>`; this never sends.
3. Run `email_cli.py send --root <workspace> --request-file <prepared.json> --output <receipt.json>` via bash, with a bounded timeout. Write requests and outputs under workspace reports/email; inspect the durable receipt even after failure or timeout. Do not create a Job or calculation Attempt for email. Preserve the installation and workspace paths; never stage credentials remotely.
4. Read the delivery receipt. `sent` means transport acceptance, not inbox delivery or reading. `already_sent` reuses a prior receipt. `unknown` requires reconciliation, never blind retries. Use `status --receipt-ref <workspace-relative receipt> --output <status.json>` to inspect it.

Host/Monitor only wakes the Agent. This Skill owns notification preparation and delivery; no native notification tool or Provider registration is required. Failed email does not undo completed science. Notification IDs must not contain a Job ID, retry time or unrelated research revision.

Finish requested delivery, or record its specific blocker, before a terminal checkpoint. A delivery Node records the outcome without a calculation Attempt. Preserve user authorization and completion conditions: a request for final results does not automatically authorize failure notices. Global blocked/terminal still stops bash; resume through an explicit recovery checkpoint before continuing.

For research workspaces, declare the delivery Node's `consumes` and typed dependencies before preparation; [delivery rules](references/email_delivery.md) show the scope and event choices. A failed or inconclusive predecessor can be consumed with a `finished` edge and an authorized progress/failure event. Preserve its actual outcome. The Node still needs completion conditions and execution admission before the first send.

`prepare` saves a `state_binding` to the consumed facts and evidence versions. Progress can be prepared before dependencies finish; completion events must already be true. If a consumed Node, result or requirement changes before send, inspect it and prepare again. Do not edit or copy `state_binding` by hand. Replaying the original sent request returns its receipt even after its Node or scope closes; it does not need a new preparation.

After send/status, register the durable `receipt_ref` with artifact_register under that Node, inspect it, and cite the returned Artifact when assessing the delivery requirement and any attached Gate. Close the delivery Node after its outcome is verified, before terminal. Registration failure requires registration recovery, not another delivery. Changed content or scope after a send attempt requires a new notification_id under the user's delivery scope; unresolved sending/unknown still requires reconciliation first.
