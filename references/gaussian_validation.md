# Gaussian Validation

Gaussian TS/Freq validation should be node-scoped.

Use `ts_backends.gaussian` for Gaussian input construction and Gaussian output
parsing. The public helper scripts are thin wrappers:

- `scripts/prepare_gaussian_ts_input.py`;
- `scripts/parse_gaussian_ts_result.py`.

Record:

- input path;
- output path;
- method and basis;
- charge and multiplicity;
- route readback diagnostics, including any mismatch between the intended
  Gaussian route and the route or effective step limits reported in the log;
- termination summary;
- number of imaginary frequencies;
- whether the imaginary mode matches the target elementary step;
- parsed energy when available.

One imaginary frequency is necessary but not sufficient for an accepted TS. The
mode must support the current phase claim, and connectivity must be validated in
a separate evidence layer.

Strict TS/Freq support requires all of:

- normal Gaussian termination in the selected job section;
- stationary point evidence;
- final convergence evidence and all convergence rows satisfied;
- exactly one imaginary frequency.

Concatenated or Link1 logs should be parsed section by section. The default is
the final Gaussian job section unless a section index is explicitly supplied.

When an input file is available, parse Gaussian results with
`--input-gjf <file>` so the validation artifact records the intended route,
the route echoed in the log, key settings such as `MaxCycle`, `MaxPoints`, and
`StepSize`, and effective step limits reported by Gaussian. A mismatch is a
diagnostic that should be registered in the node evidence and considered before
retrying or accepting the calculation.
