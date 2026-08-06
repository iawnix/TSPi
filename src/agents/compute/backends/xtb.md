# xTB Backend Policy

- Preserve charge, UHF state, solvent, method, optimization level, and input geometry.
- Supported typed tasks are `sp`, `opt`, `freq`, `opt_freq`, and `md`; MD requires a bound xTB control input.
- Report execution completion, task completion, SCC and optimization convergence, energy, geometry, frequency, trajectory, artifact-completeness, and program-failure facts separately.
- xTB may screen or refine candidates but does not establish final TS/Freq or connectivity support.
