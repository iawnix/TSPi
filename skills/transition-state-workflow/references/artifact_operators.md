# Artifact Operators

Pi exposes three fresh operational child sessions for bounded local artifacts.
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

`ts_subagent_report` accepts `operation=build` and one new
`packageRef` under `reports/`. The typed child tool calls the deterministic
report builder, which first validates the workspace and writes:

```text
<packageRef>/final_report.md
<packageRef>/report_context.json
<packageRef>/email_summary.md
<packageRef>/assets/
<packageRef>/package_manifest.json
```

The builder publishes the directory atomically and refuses overwrite. The
`ts-report-package/1` manifest binds the source scientific
`workspace_revision` and each generated file by SHA-256. The child may
summarize generated artifacts but cannot add hypotheses, acceptance decisions,
or unsupported causal claims.

## Email Draft

`ts_subagent_email_draft` accepts only `operation=draft`, a generated
`email_summary.md`, a new JSON `draftRef` under `reports/`, and explicit
recipient addresses. The selected summary must have a sibling
`report_context.json` and `package_manifest.json`. Preflight verifies the
manifest, context, and selected summary digests. The deterministic draft writer
repeats those checks so a post-preflight file change is rejected.

The child writes one local `ts-email-draft/1` artifact. The deterministic writer
parses the `Subject:` line and body directly from the manifest-bound
`email_summary.md`; the child cannot supply either field. The body is not stored
in Pi run metadata. This operator has no send, network, sender-selection,
credential, mailbox, or recipient-discovery capability.

## Fixed-Policy Delivery

`ts_email_send` is a deterministic host tool, not a child-agent capability. It
accepts only `operation=send` and an existing `draftRef`. A mode-0600 policy at
`TS_EMAIL_POLICY_ROOT` (falling back to `TS_WORKSPACE_ROOT`) fixes the
recipients, `ts-report-summary/1` template, ClawEmail skill root, and exact
package-relative attachment names. A separate mode-0600 authorization record
binds the complete policy digest after the user enters the exact activation
token returned by `policy-create`.

A research workspace may inherit an active installation policy only when its
real path is below the configured policy root. A workspace with no local policy
inherits directly; a local pending policy inherits only when its transport,
recipients, template, and attachment names exactly match. Local active,
disabled, changed, invalid, or differently scoped state takes precedence.
`policy-status` exposes the effective scope, source root, and local state.
Create, activate, and disable remain local to their explicit roots, while
delivery receipts always remain in the research workspace. `policy-disable`
revokes automatic delivery without deleting policy history; reactivation
requires the same token again.

Before delivery, the host rechecks the draft, report manifest, summary, context,
attachments, policy digest, authorization, and ClawEmail private-state modes.
It writes a digest-addressed delivery guard before invoking ClawEmail. A `sent`
receipt makes repeated calls idempotent; `sending` or `unknown` blocks automatic
retry because delivery may already have occurred. A model-supplied boolean or
free-form authorization claim is never accepted.

## Result Binding

All three roles return `ts-agent-result/1`. The host requires exactly one typed
action and rejects:

- invented or omitted artifact refs;
- payload paths, node IDs, recipients, or subjects that differ from the typed
  action result;
- facts outside the task basis allowlist;
- email body or authorization fields in the result;
- hypothesis, branch, accepted-TS/pathway, strict pathway, study-completion, or
  next-decision fields anywhere in the result.
