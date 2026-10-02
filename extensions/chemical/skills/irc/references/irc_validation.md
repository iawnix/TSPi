# IRC Validation

An intrinsic reaction coordinate calculation tests whether a selected saddle
leads toward the declared reactant and product basins. It does not by itself
prove that the terminal geometries are optimized minima.

For each direction, preserve the source saddle, direction, calculation intent,
path Artifact, endpoint Artifact, and digest. Check that the starting geometry
agrees with the validated saddle within an explicit tolerance. Inspect normal
program termination, the requested direction, path completeness, number of
steps, final geometry, final gradient when available, and any maximum-step or
short-path limitation.

`path.endpoint_summary` extracts a finite directional Gaussian IRC endpoint,
termination and completion markers, and an available starting geometry. Missing
starting geometry or an incomplete path remains inconclusive. Optimize an
endpoint when its gradient or geometry does not justify direct basin assignment.

Compare each endpoint with an explicitly selected reactant or product Artifact.
Verify element counts, atom mapping, charge, multiplicity or electronic state,
forming and breaking bonds, key internal coordinates, fragment pairing,
conformation, and stereochemistry. Use `artifact_compare` when a deterministic mapped
comparison is appropriate. Do not infer endpoint identity from filenames or
path direction alone.

`mechanism.step.audit` may combine stationary, mode, forward/reverse path, and
structure-comparison Artifacts. The expected endpoint IDs must be explicit and
each comparison must bind the extracted endpoint to that target. Treat the
audit as a structured assessment, not an automatic Claim verdict.

Record path completion and endpoint assignment separately for each direction.
Missing, ambiguous, or contradictory evidence is an IssueFinding. A Gate may
make endpoint criteria visible, but its evaluation and the resulting Node or
Claim status remain separate changes.
