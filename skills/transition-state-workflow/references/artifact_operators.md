# Artifact Operators

Pi exposes three fresh operational child sessions for bounded local artifacts.
Each child receives one private skill, one typed tool, no built-in tools, no
parent history, and no canonical workspace mutation authority.

## Render

`ts_workspace_render_operator` accepts:

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

`ts_workspace_report_operator` accepts `operation=build` and one new
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

`ts_workspace_email_operator` accepts only `operation=draft`, a generated
`email_summary.md`, a new JSON `draftRef` under `reports/`, and explicit
recipient addresses. The selected summary must have a sibling
`report_context.json` and `package_manifest.json`. Preflight verifies the
manifest, context, and selected summary digests. The deterministic draft writer
repeats those checks so a post-preflight file change is rejected.

The child writes one local `ts-email-draft/1` artifact. The body is passed to
the deterministic script through a mode-0600 temporary request file and is not
stored in Pi run metadata. This operator has no send, network, sender-selection,
credential, mailbox, or recipient-discovery capability.

Sending is a separate future integration. It must use a host-issued,
current-turn authorization capability bound to exact recipients and a fixed
draft digest. A model-supplied boolean or free-form claim of authorization is
not sufficient.

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
