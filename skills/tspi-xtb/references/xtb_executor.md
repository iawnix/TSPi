# xTB Executor Contract

The registered xTB capabilities are `xtb.sp`, `xtb.opt`, `xtb.freq`,
`xtb.opt_freq`, `xtb.scan`, and `xtb.md`. The first four require one `xyz`
input. Scan and MD require exactly one `xyz` and one `control` input.

The adapter accepts `gfn0`, `gfn1`, `gfn2`, or `gfnff`; charge and `uhf` are
explicit. Solvent and solvent model must be supplied together and the model is
`alpb` or `gbsa`. Optimization tasks accept a bounded `opt_level` and
`max_cycles`. The capability descriptor is the exact machine contract; ask
`ts_state mode=capabilities` before constructing an unfamiliar request.

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
are candidate Observations. Inspect negative-frequency displacements for mode
assignment, and refine scan maxima with stationary-point optimization and validation.
