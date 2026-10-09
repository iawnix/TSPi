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

The [Gaussian explicit-input runner](../../gaussian/SKILL.md) accepts
`--validation irc` and uses `gaussian_io.py::parse_irc_log` to write
`irc_path_summary.json`, `irc_path_points.json` and `gaussian_endpoint.xyz`.
Declare these files with the preparation helper's `--collect` when needed.
Its basic checks require path points and endpoint geometry; they do not prove
path completeness or basin identity. Optimize an endpoint when its gradient
or geometry does not justify direct assignment.

Compare each endpoint with an explicitly selected reactant or product Artifact.
Verify element counts, atom mapping, charge, multiplicity or electronic state,
forming and breaking bonds, key internal coordinates, fragment pairing,
conformation, and stereochemistry. Execute any mapped comparison with a real
analysis tool or Job and register its outputs; `artifact_derive` only records a descriptor. Do not infer endpoint identity from filenames or
path direction alone.

Combine stationary, mode, forward/reverse path and structure-comparison evidence
in an assessment. Bind each extracted endpoint to the expected Artifact explicitly.
For the declared DA path, use `chemical.gaussian_irc_connectivity` with the spec,
saddle log and both directional logs; [the executable path](../../candidate-generation/references/gaussian_path.md) documents
its origin, completion and endpoint checks. Missing checks remain unresolved;
this is not a general mechanism-audit executor.

Record the observations, scientific criteria, unresolved questions and next steps with research_update using the existing node_id and a note. Publish a reusable conclusion with research_result, citing collected materials and stating limitations. A completed computation does not establish a scientific conclusion.
