# Deterministic Artifact Tools

Render and Report are direct host tools. They start no child model, make no
scientific decision, and never mutate canonical records.

## Render

Discover logical inputs with `ts_workspace_context mode=artifacts`, then call:

```json
{
  "operation":"render",
  "actId":"act_...",
  "inputArtifactIds":["art_..."],
  "outputName":"candidate.png"
}
```

Operations are:

- `render`: exactly one input, `.png` output;
- `animate`: exactly one input, `.gif` output;
- `compare`: at least two inputs, `.png` output;
- `mechanism`: at least two inputs, `.png` output.

The host resolves IDs and digests, validates the owning Act, rejects traversal
and symlinks, allocates `acts/<act_id>/outputs/render/<outputName>`, refuses
overwrite, runs the renderer, and verifies a non-empty regular output.

An image is presentation. Scientific use requires verified source artifacts and
normal Observations; visual appearance alone is not a validation result.

## Report

Build one new package:

```json
{"operation":"build","packageName":"final-study"}
```

The host owns `reports/<packageName>`, validates the complete v4 workspace,
renders the report from canonical records, installs the directory atomically,
and verifies `package_manifest.json`, workspace revision, file list, and
SHA-256. Existing package names are never overwritten.

Reports project state; they cannot repair or complete it. Missing or
inconclusive science remains visible.

## Notify

When fixed-target notifications are enabled:

```json
{
  "operation":"send",
  "event":"act_completed",
  "subject":"TS study update",
  "summary":"The bounded validation Act completed; connectivity remains open.",
  "reportRefs":["reports/final-study/final_report.md"]
}
```

Allowed events are `progress`, `act_completed`, `calculation_failed`,
`calculation_ambiguous`, and `study_completed`. Attachments must be existing
regular files below `reports/`.

The installation owns recipient and credentials. Subject/summary text cannot
redirect delivery. The host writes a digest-bound receipt. Known success is
idempotent; ambiguous delivery is not automatically replayed. Notification
failure has no scientific effect.

## Activity And Provenance

Render and Report write deterministic activity journals. Notification writes a
delivery receipt. These records support diagnosis and reporting but do not
become Observations or acceptance basis automatically.
