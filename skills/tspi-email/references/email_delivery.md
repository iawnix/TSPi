# Email Delivery Contract

`notify.send` delivers a fixed event to the recipient owned by the TSPi
installation and records the delivery receipt.

The installation can retain the existing ClawEmail transport or use the built-in
SMTP transport. SMTP currently supports the `163` and `qq` presets:

```toml
[notifications.email]
enabled = true
provider = "smtp"
preset = "qq"                 # "163" or "qq"
recipient = "receiver@example.com"
from_address = "sender@qq.com" # optional; defaults to username
username = "sender@qq.com"
password_env = "TSPI_EMAIL_PASSWORD"
```

The password must be the provider's SMTP authorization code, not the normal
web-login password. `smtp.163.com` and `smtp.qq.com` default to port 465 with
implicit TLS; the QQ preset also accepts port 587 with `security = "starttls"`.
Password files are allowed instead of `password_env` when they are absolute,
regular files with mode 0600. The preset fixes the SMTP host; optional port and
security overrides remain installation-owned and are never accepted from a
notification request.

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
regular files listed by the exact `ts-report-package/5` manifest under
`reports/<packageName>/`. A Render file below `nodes/` must first be included by
logical artifact ID when building the report package.

Configure the recipient and credentials at installation level. The host writes
a digest-bound receipt and returns it for a repeated successful request.
For unknown delivery, inspect provider status before retrying. Delivery failures
are recorded with the notification's operational history.

This Skill is send-only. POP3 and IMAP are intentionally out of scope; they
should be added as a separate receive/mailbox capability if a future workflow
needs to read mail.
