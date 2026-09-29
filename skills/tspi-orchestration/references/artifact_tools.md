# Deterministic Artifact Tools

Structure Seed, Structure Compare, and Import are host tools for preparing and
analyzing Node-owned input artifacts.

## Contents

- [Generate A Structure Seed](#generate-a-structure-seed)
- [Compare Registered Structures](#compare-registered-structures)
- [Import An Existing Input](#import-an-existing-input)
- [Run Registered Analysis](#run-registered-analysis)
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
parity, and writes content-addressed XYZ plus provenance under the non-closed Node.
The activity request retains a SMILES digest, not the body. The provenance
records canonical SMILES, RDKit version, parameters, metadata, output digest,
and limitations. Use one connected SMILES; prepare multi-fragment encounter
geometries with an explicit arrangement and import the resulting XYZ.

Use the initial geometry for follow-up optimization and characterization.
Establish stationary-point, mode, and connectivity properties through Compute
and the relevant Gates.

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

This result is operational. Register any value used in a Claim or Node outcome
as a semantic Finding through `research_change`, citing the verified analysis artifact.

## Import An Existing Input

After starting a non-closed ResearchNode, create one bounded input with a semantic
basename. The host owns its Node-local directory:

```json
{
  "operation":"import",
  "nodeId":"node_1",
  "format":"gaussian_input",
  "inputName":"cycloaddition-ts.gjf",
  "content":"#p M062X/6-31+G(d,p) opt\n\n...\n",
  "charge":0,
  "multiplicity":1
}
```

Formats are `gaussian_input`, `xyz_structure`, and `xtb_control`. Provide a
concise semantic `inputName`; Gaussian accepts `.gjf` or `.com`, XYZ requires
`.xyz`, and xTB control requires `.inp`. Gaussian and XYZ imports require
declared charge and multiplicity. The host bounds and validates UTF-8 text,
restricts the name to a safe basename, rejects traversal and symlinks, writes a
private Node input, and returns its content-bound logical `artifactId`.
Replaying the same name and content is idempotent; the same name never
overwrites different content. The activity journal stores hashes and metadata,
never the input body. QST2/QST3 imports also require every structure to use the same
declared charge/multiplicity, atom count, and atom order. Multi-job `--Link1--`
inputs and Link 0 filesystem paths are rejected. Resolve the result with
`research_read mode=artifacts` before Compute.

## Run Registered Analysis

`analysis_run` is the deterministic, local analysis boundary. It consumes
registered Artifact IDs and writes an operational analysis Artifact; it does
not launch a program, select a local/remote environment, or update the
ResearchMap by itself. Before calling it, query the live analysis catalog:

```text
research_read mode=capabilities capabilityKind=analysis
research_read mode=capabilities capabilityKind=analysis query=chemical.name.resolve@1
```

The second form is preferred when the exact capability and version are known.
Catalog presence and the exact version are required; a missing entry is a
capability gap and cannot be bypassed by guessing a method or using an
unregistered installed tool. The request contract is:

```json
{
  "operation": "run",
  "nodeId": "node_1",
  "capability": "reaction.parse",
  "capabilityVersion": "1",
  "inputArtifacts": {
    "reactants": ["art_..."],
    "products": ["art_..."]
  },
  "parameters": {}
}
```

`nodeId` must identify an existing open ResearchNode. `inputArtifacts` is a
role-to-array mapping of registered `art_...` IDs; physical paths, arbitrary
filenames, and invented IDs are invalid. Host/Kernel resolves each ID, checks
its workspace path, digest, and input-role schema, then passes immutable bytes
to the registered provider. Bind inputs to the owning Node in the request and
preserve their returned owner/path metadata; `parameters` must satisfy that
capability's parameter schema. The name resolver accepts (among other fields) `name`, `resolver`, and
optional candidate records; automatic deterministic resolution requires its
installation-owned resolver configuration as described in the chemical-input
Skill.

The provider writes its result below
`nodes/<node_id>/outputs/analysis/` and returns a bound
`ts-analysis-result/1` with the analysis Artifact and source Artifact IDs.
Analysis does not create a Claim, Finding, Gate, or Node status transition.
Root must inspect and verify the returned Artifact, then use `research_change`
to record a narrow `FactFinding` or `IssueFinding` with `source_refs` pointing
to the registered analysis Artifact. Use `compute_run` for calculation
lifecycles, including local/remote execution; do not route a calculation
through `analysis_run`.

## Activity And Provenance

Structure Seed, Structure Compare, and Import write deterministic activity
journals whose `node_refs` are the only operation-to-Node link. Compute writes
one `sub_n` run below its owning `calc_n` Attempt. Render, Report, and Notify
have their own focused capability contracts. These records support diagnosis
and reporting. Verify their underlying artifacts when recording Findings.
