# xTB execution and native output guidance

The bundled `scripts/run.py` and preparation helper support `opt`, `sp` and
`opt-sp` with GFN2-xTB. Use their actual `--help` for accepted arguments.
Additional native xTB tasks may be run through generic Job Runtime after checking
the installed program's options, inputs and required outputs. Existing parser
functions are analysis helpers, not an automatically invoked workflow adapter.

The scan syntax and output checklist below are scientific/native-program guidance;
they do not add `freq`, `scan` or `md` options to the bundled runner.

For `xtb.scan`, the control artifact must contain a `$scan` section and end
with `$end`. A `$end` after `$constrain` may also be used as a block separator.
The recommended numbered form defines atom indices in
`$constrain`; each `$scan` directive then refers to the 1-based position of
that constraint and contains only `start`, `end`, and `steps`:

```text
$constrain
  force constant=0.5
  distance: 5, 12, auto
$scan
  mode=sequential
  1: 1.5, 3.2, 18
$end
```

Do not repeat `5, 12` in the numbered `$scan` line. All three scan values must
be on one comma-separated line; keyword-style or multi-line
`start`/`end`/`steps` fields are not part of the adapter contract. The native
named-inline form is also supported when a scan-specific constraint is more
convenient:

```text
$scan
  distance: 5, 12, auto; 1.5, 3.2, 18
$end
```

Expected primary artifacts are:

| Task | Required artifacts |
| --- | --- |
| `sp` | `xtb.out` |
| `opt` | `xtbopt.xyz`, `xtb.out` |
| `freq` | `vibspectrum`, `xtb.out` |
| `opt_freq` | `xtbopt.xyz`, `vibspectrum`, `xtb.out` |
| `scan` | `xtbscan.log`, `xtbopt.xyz`, `xtb.out` |
| `md` | `xtb.trj`, `xtb.out` |

The parser reports execution, termination, SCC convergence when applicable,
energies, geometry, frequencies, scan points, and trajectory summaries. These
are candidate research notes. Inspect negative-frequency displacements for mode
assignment, and refine scan maxima with stationary-point optimization and validation.
