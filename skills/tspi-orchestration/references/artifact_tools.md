# Deterministic Artifact Tools

Structure Seed, Structure Compare, and Import are direct host tools. They start
no child model, make no scientific decision, and never mutate canonical records.

## Contents

- [Generate A Structure Seed](#generate-a-structure-seed)
- [Compare Registered Structures](#compare-registered-structures)
- [Import An Existing Input](#import-an-existing-input)
- [Activity And Provenance](#activity-and-provenance)

## Generate A Structure Seed

For one connected molecule described by SMILES:

```json
{
  "operation":"generate",
  "nodeId":"node_1",
  "smiles":"C1=CCCCC1",
  "charge":0,
  "multiplicity":1,
  "optimization":"uff"
}
```

`optimization` is `none` or `uff`. The host fixes RDKit ETKDGv3 parameters and
random seed, adds explicit hydrogens, checks formal charge and electron-count
parity, and writes content-addressed XYZ plus provenance under the open Node.
The activity request retains a SMILES digest, not the body. The provenance
records canonical SMILES, RDKit version, parameters, metadata, output digest,
and limitations. Multi-fragment SMILES are rejected because this tool does not
choose a reactive encounter geometry.

This output is only an initial geometry. Neither ETKDG coordinates nor UFF
energy establishes a stationary point, transition state, mechanism, or
acceptance fact. Use normal Compute and validation afterward.

## Compare Registered Structures

Compare exactly two registered XYZ artifacts:

```json
{
  "operation":"compare",
  "nodeId":"node_1",
  "referenceArtifactId":"art_...",
  "targetArtifactId":"art_...",
  "parameters":{
    "atomMapping":[0,1,2],
    "reactionCenterAtoms":[0,1,2],
    "keyBonds":[[0,1]],
    "keyAngles":[[1,0,2]],
    "keyDihedrals":[],
    "stereochemicalChecks":[],
    "rmsdThreshold":0.5,
    "reactionCenterThreshold":0.25
  }
}
```

All atom indices are zero-based. `parameters` is optional; detailed checks are
validated by the deterministic Python kernel so their schema does not consume
every Root turn. Omitted thresholds default to 0.5 and 0.25 angstrom. The host
binds both input IDs and digests and writes an idempotent private JSON artifact
under `nodes/<node_id>/outputs/analysis/`. The document includes the expanded
parameters, verdict, uncertainty, RMSD/internal-coordinate/stereochemical
metrics, diagnostics, and provenance.

This result is operational. Register any value used in a Claim or ProofSpec as a
semantic Observation through a Decision; do not cite the activity itself as
scientific evidence.

## Import An Existing Input

After starting an open ResearchNode, create one bounded seed without choosing a
path or filename:

```json
{
  "operation":"import",
  "nodeId":"node_1",
  "format":"gaussian_input",
  "content":"#p M062X/6-31+G(d,p) opt\n\n...\n",
  "charge":0,
  "multiplicity":1
}
```

Formats are `gaussian_input`, `xyz_structure`, and `xtb_control`. Gaussian and
XYZ imports require declared charge and multiplicity. The host bounds and
validates UTF-8 text, rejects traversal and symlinks, generates a private
content-addressed Node input, and returns its logical `artifactId`. Identical
replay is idempotent. The activity journal stores hashes and metadata, never
the input body. QST2/QST3 imports also require every structure to use the same
declared charge/multiplicity, atom count, and atom order. Multi-job `--Link1--`
inputs and Link 0 filesystem paths are rejected. Resolve the result with
`ts_state mode=artifacts` before Compute.

## Activity And Provenance

Structure Seed, Structure Compare, and Import write deterministic activity
journals whose `node_refs` are the only operation-to-Node link. Compute writes
one `sub_n` run below its owning `calc_n` Attempt. Render, Report, and Notify
have their own focused capability contracts. These records support diagnosis
and reporting but do not become Observations or acceptance basis automatically.
