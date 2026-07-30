# Candidate Search

`node_type=candidate_search` generates structures under a known mechanism
hypothesis. It does not establish TS/Freq validity or connectivity.

Required context:

- `hypothesis_ref` and relevant prediction IDs;
- `candidate_kind=transition_state|endpoint_conformer|intermediate|crossing_point`;
- reaction-center forming and breaking bonds;
- charge, multiplicity, atom mapping, and state assumptions;
- allowed and forbidden local contacts, key angles, valence/coordination, and
  spectator constraints;
- explicit output and ranking criteria.

Reactant/product endpoints define the target connectivity basins for later
validation. They do not determine the search method. Do not default to QST2/QST3 merely because reactant and product structures are
available. Prefer QST2/QST3 only when the endpoints are optimized, atom mapping
is reliable, conformations are compatible, and the model is one elementary
step. Otherwise compare scans, NEB/string, dimer/eigenvector following,
conformer/intermediate search, or a justified crossing-point method.

Common candidate strategies:

- constrained or relaxed scans for simple reaction coordinates;
- NEB or string methods for coupled changes;
- conformer/pose generation for uncertain endpoint geometry;
- intermediate search for stepwise hypotheses;
- QST-like or dimer searches for compatible endpoint-based guesses;
- crossing-point searches only for a declared multi-surface hypothesis.

## Endpoint Conformers

Endpoint conformer work is `candidate_kind=endpoint_conformer`. Preserve graph,
atom mapping, charge, multiplicity, and stereochemistry. Register ensemble,
selection, identity, and minimum evidence separately.

Selected endpoint conformers define usable basin representatives only. They are
not TS candidates, TS/Freq evidence, or connectivity proof.

## Ranking

A candidate that only satisfies target bond distances is not automatically
chemically plausible. Record:

- local geometry consistency: neighbors, unintended short contacts, angles,
  valence/coordination, folding, and spectator drift;
- available electronic consistency: charges, spin populations, occupations,
  state character, or hypothesis-specific diagnostics;
- explicit contradiction reasons when another local motif, proton transfer,
  state, or reaction center is found.

Contradictory candidates may remain as rejected artifacts. Do not promote them
to TS/Freq work as plausible seeds.

Close candidate search with program facts and evidence refs only. The Root Agent
selects candidates and opens a separate `validation/tsfreq` node.
