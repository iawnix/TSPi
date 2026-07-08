# Gaussian Validation

Gaussian TS/Freq validation should be node-scoped.

Use `ts_backends.gaussian` for Gaussian input construction and Gaussian output
parsing. The public helper scripts are thin wrappers:

- `scripts/ts_backend.py gaussian prepare`;
- `scripts/ts_backend.py gaussian parse`.

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
- whether the final TS geometry still matches the declared local reaction-center
  motif, including unintended short contacts, key angles, coordination or
  valence changes, and spectator drift;
- whether available electronic diagnostics support or at least do not refute
  the mechanism, such as reaction-center charges, spin density, natural orbital
  occupation, TD-state character, or charge-transfer indicators;
- parsed energy when available.

One imaginary frequency is necessary but not sufficient for an accepted TS. The
mode must support the current phase claim, the final local geometry and
available electronic diagnostics must not contradict the mechanism, and
connectivity must be validated in a separate evidence layer.

Strict TS/Freq support requires all of:

- normal Gaussian termination in the selected job section;
- stationary point evidence;
- final convergence evidence and all convergence rows satisfied;
- exactly one imaginary frequency.

Strict TS/Freq support for a mechanism claim also requires a node-scoped
mode-assignment artifact that includes local-geometry and available
electronic-structure consistency fields. If those diagnostics show that the
stationary point belongs to a different local motif, electronic state, charge
distribution, or spin pattern than the declared hypothesis, the TS/Freq node
should close as refuted or inconclusive even if it has exactly one imaginary
frequency. Do not start IRC from a TS/Freq result whose mechanism-consistency
review is refuted.

Concatenated or Link1 logs should be parsed section by section. The default is
the final Gaussian job section unless a section index is explicitly supplied.
Within the selected job section, if Gaussian printed multiple frequency tables
such as Opt=CalcAll force-constant updates followed by the final harmonic Freq
section, gate TS/Freq validity against the final complete frequency table only.
Earlier frequency tables remain useful audit diagnostics and should be retained
in the parsed artifact as raw frequency information rather than mixed into the
acceptance count.

When an input file is available, parse Gaussian results with
`--input-gjf <file>` so the validation artifact records the intended route,
the route echoed in the log, key settings such as `MaxCycle`, `MaxPoints`, and
`StepSize`, and effective step limits reported by Gaussian. A mismatch is a
diagnostic that should be registered in the node evidence and considered before
retrying or accepting the calculation.
