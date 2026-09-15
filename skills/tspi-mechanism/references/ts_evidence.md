# TS candidates, stationary points and paths

`gaussian.input.build` writes an input for one explicitly selected task: `sp`,
`opt`, `ts`, `freq`, `opt_freq`, `qst2`, `qst3`, or directional `irc`. Supply
charge, multiplicity, method, basis, and atom-aligned structures. QST2 uses two
geometries; QST3 uses reactant, product, and candidate in that order. This bounded
builder covers common routes. Advanced arbitrary routes remain available through
the existing Gaussian input import capability. Launch generated `.gjf` files
through the existing Gaussian `ts_calc` capability; construction does not submit.

`path.extract_candidate` accepts a multiframe XYZ trajectory. Select an explicit
frame index, or supply every image's energy and unit for highest-energy selection.
The result is a candidate geometry, not a verified TS. NEB convergence, an image
maximum, optimizer success and a first-order saddle are distinct facts.

`gaussian.output.analyze` reads a selected Gaussian job section (`section_index`
is zero based). The default follows the existing final-section parser. It
extracts convergence, termination, stationary markers, frequencies, geometry and
normal-mode vectors. Missing evidence is not success. Raw program facts can be
promoted individually; the analysis verdict does not accept a Claim.

`vibration.analyze_mode` needs that evidence plus a zero-based `mode_index` and
explicit atom-pair/sign expectations in `bonds`. It reports bond-length
derivatives and absolute cosine overlap; overall mode sign is arbitrary. A
single selected bond cannot discriminate competing collective motions. Choose
enough chemically relevant coordinates and inspect the displacement vectors.
The version-1 metric is not a mass-weighted full reaction-coordinate overlap.

`path.endpoint_summary` extracts a finite directional Gaussian IRC endpoint,
termination/completion markers and an available starting geometry. An endpoint
is not automatically an optimized basin. Optimize or compare as appropriate.

`mechanism.step.audit` combines selected stationary/mode/forward/reverse artifacts
and existing `ts_compare` results. `forward_species_artifact_id` and
`reverse_species_artifact_id` explicitly identify the expected endpoint targets;
the comparison must bind the extracted endpoint and that target. Initial IRC
geometry must agree with the selected TS within `origin_tolerance_angstrom`.
Missing starting geometry, path, mode or endpoint evidence remains inconclusive;
contradictions are invalid. No one chooses endpoint identities from a filename.

The audit supports structural evidence only. Confirm method/electronic state,
intended species, stereochemistry and applicable ProofSpec independently before
accepting an elementary-step Claim. Several Nodes may provide these facts.
