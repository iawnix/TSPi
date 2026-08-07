# Backend Contract

`ts_backends` prepares and describes calculation tasks. A backend may create
inputs, commands, and parsers for its own artifacts.

Backends must not:

- mutate workspace root state files;
- close a node;
- set a scientific verdict;
- accept or reject a pathway;
- write outside the node artifact directory by default.

The expected flow is:

1. `start_node` creates `nodes/<node_id>/`.
2. Backend prepares node-scoped inputs and command metadata.
3. Local or remote execution creates artifacts.
4. Parsed facts are registered through `update_workspace`.
5. `end_node` writes the closure and triggers finalizers.

Deterministic parsers may consume multiple files only when every file is bound
by the prepared attempt manifest and resides beside the selected primary
artifact. The parser records a digest for each consumed input. It must report
execution completion, requested-task completion, convergence, and artifact
completeness separately.

xTB supports `sp`, `opt`, `freq`, `opt_freq`, `scan`, and `md`. A scan binds
exactly one XYZ input and one control input. The control file is limited to
numbered distance, angle, or dihedral constraints in `$constrain` and sequential
or concerted directives in `$scan`; arbitrary xTB sections and command arguments
remain forbidden. Scan parsing binds `xtb.out`, `xtbscan.log`, `xtbopt.xyz`, and
the control input, and reports target coordinates, geometry-derived actual
coordinates, and energies without embedding full structures in JSON. CREST is a
separate `crest/conformer_search` backend because its command lifecycle and
ensemble artifacts are not xTB task artifacts.
