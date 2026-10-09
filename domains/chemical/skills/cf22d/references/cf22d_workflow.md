# CF22D workflow

The installed scripts/run.py accepts XYZ in angstrom, charge, PySCF spin (2S), basis, grid level, SCF thresholds, optimization step limit, threads and memory. Use --help for supported flags; --xc only accepts CF22D. Defaults are grid level 6, SCF tolerance 1e-10, 400 cycles and def2-tzvp; override basis explicitly for a requested comparison.

Supported tasks: sp, opt, opt-sp, ts, freq, thermo, opt_freq, ts_freq. opt-sp has separate opt and sp directories and binds the final optimized geometry to the SP input digest. The restored opt runner also evaluates a final SCF; that does not remove the explicit SP in opt-sp. Frequency and thermo tasks require converged SCF. TS workflows preserve the source default initial Hessian unless explicitly disabled.

Every run uses a new empty output directory. result.json and geometry.xyz are aggregate outputs; each step retains pyscf.out, pyscf_result.json and requested geometry/frequency/Hessian/thermochemistry artifacts. Scratch is retained in the attempt directory for diagnosis and may be cleaned after the process exits; never delete an installation scratch root. Script and input hashes bind the result. No script writes Research Memory.

Verify execution_completed, SCF convergence, structured optimization convergence and the requested task artifacts. Preserve energy units and actual versions. Reject non-finite energies and mismatched method/basis/input. The Agent separately registers research notes and evidence.

A stationary-point frequency count is not mode assignment, endpoint identity or IRC. A significant imaginary-frequency threshold defaults to -20 cm^-1. No frequency calculation means no verified minimum claim. This runner does not implement IRC, NEB, reaction scans, crossing points or multi-structure comparisons. Report missing support without substituting RHF or another functional.
