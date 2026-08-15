# Gaussian Validation

Gaussian TS/Freq validation should be node-scoped.

Use `ts_backends.gaussian` for Gaussian input construction and Gaussian output
parsing. The public helper scripts are thin wrappers:

- `python "$TS_AGENT_SKILL_ROOT/scripts/ts_backend.py" gaussian prepare`;
- `python "$TS_AGENT_SKILL_ROOT/scripts/ts_backend.py" gaussian parse`.

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
- parsed electronic energy, zero-point correction, E+ZPE, and thermal
  free-energy correction when available.

One imaginary frequency is necessary but not sufficient for an accepted TS. The
mode should support the target Claim's declared reaction coordinate, the final
local geometry and relevant electronic diagnostics must not contradict that
Claim, and connectivity must be registered and evaluated from a separate
Evidence record.

Strict TS/Freq support requires all of:

- normal Gaussian termination in the selected job section;
- stationary point evidence;
- final convergence evidence and all convergence rows satisfied;
- exactly one imaginary frequency.

When the target Claim requires `mode_assignment`, register a Node-owned
mode-assignment Evidence record and evaluate that Gate separately. Add
electronic-structure or state-character Gates when the Claim requires them. If
those diagnostics show that the stationary point belongs to a different local
motif, electronic state, charge distribution, or spin pattern, close the Node
with an explicit contradicted or inconclusive Claim update even if it has
exactly one imaginary frequency. Do not start IRC from a result whose declared
reaction-coordinate assignment is contradicted.

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

The parser normalizes Gaussian route echo wrapping before checking keywords,
including splits such as `Fre q`, `Ultra Fine`, and `Ultr aFine`. Route
`MaxCycle` is the requested optimizer setting; Gaussian's internal effective
step maxima are runtime diagnostics and are not required to repeat that number.
Do not report `maxcycle_not_seen_in_effective_step_limits` merely because these
two concepts differ.

For IRC, Gaussian point 0 is a TS path marker and may have no `CURRENT
STRUCTURE` block. The deterministic IRC parser excludes a coordinate-free point
0 and begins the coordinate series at point 1. It writes the path summary,
point table, and final endpoint XYZ without interpreting endpoint identity.
