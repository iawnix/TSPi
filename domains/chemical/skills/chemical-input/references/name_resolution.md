# Name lookup and Agent inference

## Lookup

Prepare `chemical.resolve@1` with `--name ORIGINAL` and optionally `--lookup-name NORMALIZED`.
The original name stays in the result. Every name uses the same lookup path.
The default order is PubChem then OPSIN; an explicit installation preference goes first.
A backend yielding usable candidates completes lookup. If its results cannot be parsed,
continue to the next backend. Each enabled backend is attempted once per invocation;
404, rate limits, timeout and malformed responses retain their diagnostics.
Use a purposeful translated/normalized query if helpful, then infer candidates when
further lookup is unlikely to add information.

Configuration comes from CORAGENT_NAME_RESOLVER_CONFIG or
CORAGENT_INSTALL_ROOT/etc/name-resolver.toml. Managed Jobs receive explicit
bindings: the installer sets the local structure backend's resolver path in job.toml.
Explicit settings are preserved; remote targets require a path readable on that target.
Prepare a new request after changing a binding. Missing configuration returns
`next_step=infer_candidates`, allowing the Agent to continue from the description.

## Candidate input

The current Agent writes a JSON document and prepares `chemical.resolve-candidates@1`
with `--input candidates=<file>`. The Job stages the file and pins its digest.
It checks structures locally, without a model API call or another service lookup.

```json
{
  "name": "ethanol",
  "lookup_name": "ethanol",
  "candidates": [
    {
      "smiles": "CCO",
      "source": "llm",
      "reason": "Two-carbon alcohol with a terminal hydroxyl group.",
      "assumptions": ["Neutral molecule."],
      "charge": 0,
      "multiplicity": 1
    }
  ]
}
```

`name` and a non-empty `candidates` list are required. `lookup_name` is optional;
`lookup_ref` may reference the preceding collected lookup. Supply up to 16 candidates
in a file of at most 1 MiB. Each candidate requires `smiles` and `source` (`llm` or `user`).
`reason`, `assumptions`, `charge` and `multiplicity` are optional. Record the short
basis and relevant assumptions for Agent inferences. Charge is computed from the
SMILES; if supplied, charge and multiplicity are checked for consistency.
User-supplied SMILES can also go directly through inspect/seed without this file.

## Results and next actions

Results keep `schema_version=chemical-input/1` and the existing data/candidate fields.
The `source` field records where a structure came from. Source alone does not change
its status or require confirmation. Earlier stored results remain readable as recorded.

- `resolved` / `prepare_geometry`: one usable structure; generate its initial geometry.
- `ambiguous` / `select_or_enumerate`: alternatives or unspecified stereo; choose with
  a stated basis or explore branches consistent with the user's research scope.
- `unresolved` / `infer_candidates`: lookup produced no usable structure; let the Agent infer it.
- `unresolved` / `revise_candidates`: proposed structures failed checks; repair the reported issues.

`checks` contains per-candidate findings; `diagnostics` preserves lookup and repair details.
Usable candidates retain canonical/isomeric SMILES, formula, charge, stereo information,
source, optional rationale/assumptions and multiplicity. Candidate-file SHA256 and optional
lookup reference appear in `input_provenance`; service evidence is in `resolver_provenance`.

Use a chosen candidate's canonical SMILES, charge and chosen multiplicity with
`chemical.seed@1`, adding `--enumerate-stereo` when studying stereochemical alternatives.
There is no additional confirmation step for an LLM-sourced structure. Keep its source
and assumptions with the generated geometry and subsequent research results.
