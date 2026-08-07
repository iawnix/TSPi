# xTB Backend Policy

- Preserve charge, UHF state, solvent, method, optimization level, and input geometry.
- Supported typed tasks are `sp`, `opt`, `freq`, `opt_freq`, `scan`, and `md`; scan and MD require a bound xTB control input.
- Scan control is restricted to numbered distance, angle, and dihedral constraints in `$constrain` plus sequential or concerted `$scan` directives. Do not request arbitrary control sections or command arguments.
- Report execution completion, task completion, SCC and optimization convergence, energy, geometry, frequency, scan-point target and actual coordinates, trajectory, artifact-completeness, and program-failure facts separately.
- xTB may screen or refine candidates but does not establish final TS/Freq or connectivity support.
