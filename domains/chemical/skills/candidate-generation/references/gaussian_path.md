# Executable mapped DA path

`../scripts/prepare_path.py` implements one bounded path: explicit neutral-carbon
Diels–Alder topology, mapped reactant/product seeds, Gaussian QST2+Freq, and
forward/reverse IRC from the collected TS checkpoint. It supports closed-shell
singlets without isotope-specific masses. Specify reactant stereochemistry;
unspecified product stereochemistry can be enumerated, at most 16 variants.
This path does not implement NEB, exhaustive conformer search or complete mechanism discovery.

Create and register a `chemical-path-spec/1` JSON artifact, for example:

```json
{
  "schema_version": "chemical-path-spec/1",
  "mapped_smiles": "[CH2:1]=[CH:2][CH:3]=[CH2:4].[CH2:5]=[CH:6][CH3:7]>>[CH2:1]1[CH:2]=[CH:3][CH2:4][CH2:5][CH:6]1[CH3:7]",
  "transformation": {
    "kind": "diels_alder",
    "diene": [1, 2, 3, 4], "dienophile": [5, 6],
    "forming_bonds": [[1, 6], [4, 5]]
  },
  "method": "M062X", "basis": "6-31G**", "charge": 0,
  "multiplicity": 1, "threads": 12, "memory_mb": 4000
}
```

Use the actual listed Skill paths and workspace paths in these commands:

```text
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.path-candidates --version 1 --input spec=<workspace>/spec.json --input-artifact <spec-ref> --output <workspace>/candidates-request.json -- --enumerate-stereo --conformers 2
```

Submit the returned request_file/request_sha256 and collect the Job before inspecting candidates. The entry uses the target structure binding; all generated files are collected with Job provenance.

`candidates.json` lists every prepared or failed branch. Each successful branch
contains `spec.json`, `atom_order.json`, `reactants.xyz`, `product.xyz` and `ts.gjf`
with hashes. The helper embeds product conformers, constructs an s-cis diene and
aligns/separates reactant fragments while retaining atom correspondence. These
are unoptimized endpoint seeds. Keep failed branches and inspect the inputs;
QST2 convergence and completeness of the finite candidate set are not guaranteed.
Register each selected branch's spec and geometries. The branch spec is the subject
of the `chemical.diels_alder_path@1` acceptance profile; evidence for different
spec artifacts cannot be mixed to satisfy one path.
The generated `ResearchAgentSpec` title binds the solver output to the branch spec digest.
Keep that title in the TS input and checkpoint; raw TS and IRC logs must echo it.

Prepare a TS request with the existing method-selection helper:

```text
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config <installation>/job.toml --environment local --executor chemical.gaussian-input --version 1 --input input=<branch>/ts.gjf --collect results/ts.chk --output <workspace>/ts-request.json -- --method M062X --basis '6-31G**' --threads 12 --memory-mb 4000 --validation saddle
```

Submit the returned `request_file` and `request_sha256` through `job_start`.
Collect the terminal Job. A successful runner is not a scientific verdict:
validate the raw collected `gaussian.out` with the registered saddle validator.
Inspect the checks and their scope before choosing the next experiment. A parser failure is not a scientific rejection and does not prohibit further exploration. Record missing evidence and your rationale; do not describe unresolved checks as passed. When IRC is the chosen next step, prepare inputs from that Job's collected `ts.chk`:

```text
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.path-irc --version 1 --input spec=<branch>/spec.json --input checkpoint=<collected-ts.chk> --input-artifact <spec-ref> --input-artifact <checkpoint-ref> --output <workspace>/irc-request.json
```

Submit and collect the IRC-input Job before using its generated inputs and checkpoint.

For each direction, use `-m research_agent.application.executors --executor chemical.gaussian-input --version 1 --input input=<workspace>/irc/forward.gjf`
(or `reverse.gjf`), `--dependency <workspace>/irc/ts.chk=ts.chk`, and
`--collect results/irc_path_summary.json --collect results/irc_path_points.json --collect results/gaussian_endpoint.xyz`.
Keep the same method/resources and use `--validation irc` after `--`.
Submit each returned reference, collect both results, then validate connectivity.

Registered validators use `job_start(validator_id=..., input_artifact_ids=[...])`:

| Validator, version 1 | Ordered input Artifact IDs |
| --- | --- |
| `chemical.reaction_mapping` | registered branch spec |
| `chemical.gaussian_saddle` | branch spec, collected saddle Gaussian log |
| `chemical.gaussian_irc_connectivity` | branch spec, saddle log, forward IRC log, reverse IRC log |

Input schemas, hashes and producer receipt versions are checked before execution.
The mapping validator checks the entire bond-change pattern and per-atom hydrogen
counts. The saddle validator checks route, charge/spin, processor/memory readback,
convergence, a complete frequency table and same-sign forming-bond displacement.
The IRC validator rechecks that saddle, completed directional paths, starting
geometry RMSD ≤ 0.05 Å, and distinct mapped reactant/product endpoint connectivity.
Ambiguous covalent distances or missing fields do not pass. Endpoint checks cover
explicit atom stereocenters, not a general stereochemical mechanism proof or bond-order recovery.

Gaussian parsing currently requires ordinary Cartesian orientation tables,
`Atom AN X Y Z` harmonic modes and coordinate-bearing IRC `CURRENT STRUCTURE`
blocks. Unsupported output formats, incomplete paths or missing resource readback
need review; do not replace them with a passing Agent assessment. Tests execute
these real helpers, parsers and Jobs with synthetic solver output. They do not
establish that an actual Gaussian search converges for every candidate.
