# Artifact Operators And User Notifications

Pi exposes two fresh operational child sessions for bounded local artifacts.
Each child receives the shared artifact policy, one selected role policy, one
typed tool, no built-in tools, no parent history, and no canonical workspace
mutation authority. Policy fragments are not Pi skills.

## Render

`ts_subagent_render` accepts:

- `operation=render|compare|animate|mechanism`;
- one owning `nodeId`;
- existing workspace-relative `inputRefs` under `inputs/` or `nodes/`;
- one new `outputRef` under `nodes/<nodeId>/outputs/`.

Still images use PNG/JPEG output; animation uses GIF. The request rejects
absolute paths, parent traversal, symlink components, missing inputs, and
overwriting an existing artifact. A rendered image remains a visualization
artifact; scientific support must come from verified source calculations that
the Root Agent registers separately.

## Report

`ts_subagent_report` accepts `operation=build` and one new `packageRef` under
`reports/`. The typed child tool calls the deterministic report builder, which
first validates the workspace and writes:

```text
<packageRef>/final_report.md
<packageRef>/report_context.json
<packageRef>/email_summary.md
<packageRef>/assets/
<packageRef>/package_manifest.json
```

The builder publishes the directory atomically and refuses overwrite. The
`ts-report-package/1` manifest binds the source scientific
`workspace_revision` and each generated file by SHA-256. The host generates the
complete child result from the typed action; the model does not restate artifact
refs, facts, payloads, or provenance. `email_summary.md` remains part of the
report package; notification delivery does not require an intermediate draft
JSON.

## Notify User

`ts_notify_user` is a deterministic Root Agent tool, not a child-agent role. It
accepts:

- `operation=send`;
- `event=progress|node_completed|calculation_failed|calculation_ambiguous|study_completed`;
- a bounded subject and research summary;
- up to eight optional existing regular-file `reportRefs` under `reports/`.

The Agent cannot pass a recipient, sender, mailbox, credentials, transport
configuration, or arbitrary filesystem path. The host reads one mode-0600
installation config from `TS_NOTIFICATION_CONFIG`:

```toml
[notifications.email]
enabled = true
recipient = "researcher@example.org"
clawemail_root = "/home/iaw/.pi/agent/skills/clawemail"
```

That installation config is the persistent authorization for notifications;
there is no activation token, per-message confirmation, or recipient
allowlist. Setting `enabled=false` disables delivery. ClawEmail authentication
remains private to the configured ClawEmail installation.

TSPi exposes the configured recipient as display-only session metadata in the
startup UI and `ts_notify_user` description. This lets the Root Agent detect a
user-requested target mismatch before calling the tool. Message text cannot
override the target. The Root Agent must not edit or promise to edit this
installation-owned configuration; a mismatch is reported for the host operator
and the notification is not sent.

Before network activity, the host binds the event, subject, summary, workspace
identity/revision, configuration digest, and attachment digests into a
notification digest and writes a receipt guard under
`reports/email/deliveries/`. A `sent` receipt makes repeated calls idempotent.
If the provider process started but its result is unclear, the receipt becomes
`unknown` and automatic retry is rejected. A failure before provider start is
recorded as `failed` and may be retried after the local cause is repaired.

Notification output and receipts omit the recipient, ClawEmail path, message
summary, and credentials. Notification failure never mutates canonical
workspace state, changes evidence, or blocks scientific progress.

## Result Binding

Render and report roles return host-generated `ts-agent-result/1` records. The
host requires exactly one typed action, accepts success only from the canonical
`rendered` or `built` state, and rejects:

- invented or omitted artifact refs;
- payload paths or node IDs that differ from the typed action result;
- a reported render success without a nonempty bound output file;
- a report package whose manifest digest, source workspace revision, required
  files, file sizes, or file SHA-256 values do not match the generated output;
- hypothesis, branch, accepted-TS/pathway, strict pathway, study-completion, or
  next-decision fields anywhere in the result.
