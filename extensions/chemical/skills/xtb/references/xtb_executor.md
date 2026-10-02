# xTB Executor Contract

The registered xTB capabilities are `xtb.sp`, `xtb.opt`, `xtb.freq`,
`xtb.opt_freq`, `xtb.scan`, and `xtb.md`. The first four require one `xyz`
input. Scan and MD require exactly one `xyz` and one `control` input.

The adapter accepts `gfn0`, `gfn1`, `gfn2`, or `gfnff`; charge and `uhf` are
explicit. Solvent and solvent model must be supplied together and the model is
`alpb` or `gbsa`. Optimization tasks accept a bounded `opt_level` and
`max_cycles`. The capability descriptor is the exact machine contract; ask
`research_read mode=capabilities` before constructing an unfamiliar request.

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
are candidate Findings. Inspect negative-frequency displacements for mode
assignment, and refine scan maxima with stationary-point optimization and validation.
