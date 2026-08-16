# Deterministic Artifact Tools

Structure Seed, Import, Render, and Report are direct host tools. They start no child model,
make no scientific decision, and never mutate canonical records.

## Contents

- [Generate A Structure Seed](#generate-a-structure-seed)
- [Import An Existing Input](#import-an-existing-input)
- [Render](#render)
- [Report](#report)
- [Notify](#notify)
- [Activity And Provenance](#activity-and-provenance)

## Generate A Structure Seed

For one connected molecule described by SMILES:

```json
{
  "operation":"generate",
  "actId":"act_1",
  "smiles":"C1=CCCCC1",
  "charge":0,
  "multiplicity":1,
  "optimization":"uff"
}
```

`optimization` is `none` or `uff`. The host fixes RDKit ETKDGv3 parameters and
random seed, adds explicit hydrogens, checks formal charge and electron-count
parity, and writes content-addressed XYZ plus provenance under the open Act.
The activity request retains a SMILES digest, not the body. The provenance
records canonical SMILES, RDKit version, parameters, metadata, output digest,
and limitations. Multi-fragment SMILES are rejected because this tool does not
choose a reactive encounter geometry.

This output is only an initial geometry. Neither ETKDG coordinates nor UFF
energy establishes a stationary point, transition state, mechanism, or
acceptance fact. Use normal Compute and validation afterward.

## Import An Existing Input

After starting an open ResearchAct, create one bounded seed without choosing a
path or filename:

```json
{
  "operation":"import",
  "actId":"act_1",
  "format":"gaussian_input",
  "content":"#p M062X/6-31+G(d,p) opt\n\n...\n",
  "charge":0,
  "multiplicity":1
}
```

Formats are `gaussian_input`, `xyz_structure`, and `xtb_control`. Gaussian and
XYZ imports require declared charge and multiplicity. The host bounds and
validates UTF-8 text, rejects traversal and symlinks, generates a private
content-addressed Act input, and returns its logical `artifactId`. Identical
replay is idempotent. The activity journal stores hashes and metadata, never
the input body. QST2/QST3 imports also require every structure to use the same
declared charge/multiplicity, atom count, and atom order. Multi-job `--Link1--`
inputs and Link 0 filesystem paths are rejected. Resolve the result with
`ts_workspace_context mode=artifacts` before Compute.

## Render

Discover logical inputs with `ts_workspace_context mode=artifacts`, then call:

```json
{
  "operation":"render",
  "actId":"act_1",
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
and verifies `package_manifest.json`, scientific and operational revisions,
file list, and SHA-256. Existing package names are never overwritten. The
caller's in-flight Report activity is explicitly excluded from its own snapshot.

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

Compute, Structure Seed, Import, Render, and Report write deterministic activity journals whose
`act_refs` are the only operation-to-Act link. Notification writes a delivery
receipt. These records support diagnosis and reporting but do not become
Observations or acceptance basis automatically.
