# xTB execution and interpretation

## Choose an execution route

`chemical.xtb@1` is a GFN2-xTB convenience wrapper for `sp`, `opt`, and `opt-sp`.
For other native tasks, use a generic `job_start` command or a task script prepared
with `--script`. Neither requires adding an entry to `execution.json`.
Follow the [Job contract](../../method-selection/references/backend_contract.md):
select the target platform, executable/activation, inputs, resources, and outputs.
Check the installed target version's help; local and remote versions may differ.

These native command examples assume `input.xyz`, a neutral singlet, and an executable
resolved in the target environment. Execute inside the Job directory and capture
stdout/stderr as `xtb.out`; adapt `--chrg`, `--uhf`, and other settings to the system.

| Task | Native command example | Primary materials to collect |
| --- | --- | --- |
| Single point | `xtb input.xyz --gfn 2 --sp --chrg 0 --uhf 0` | `xtb.out` |
| Optimization | `xtb input.xyz --gfn 2 --opt tight --chrg 0 --uhf 0` | `xtbopt.xyz`, `xtb.out` |
| Frequencies/Hessian | `xtb input.xyz --gfn 2 --hess --chrg 0 --uhf 0` | `vibspectrum`, `hessian`, `xtb.out`, available mode displacements |
| Optimization then frequencies | `xtb input.xyz --gfn 2 --ohess --chrg 0 --uhf 0` | `xtbopt.xyz`, `vibspectrum`, `hessian`, `xtb.out` |
| Constrained scan | `xtb input.xyz --gfn 2 --opt tight --input scan.inp --chrg 0 --uhf 0` | `scan.inp`, `xtbscan.log`, `xtbopt.xyz`, `xtb.out` |
| Molecular dynamics | `xtb input.xyz --gfn 2 --md --input md.inp --chrg 0 --uhf 0` | `md.inp`, `xtb.trj`, `xtb.out`, available energy/temperature records |

## Frequencies

`--hess` evaluates the supplied geometry; `--ohess` optimizes first. A minimum
assignment requires stationary-point evidence. Preserve the frequency table,
geometry, and displacement vectors. Frequency counts do not establish mode
character; discuss low-frequency noise and convergence thresholds separately.

## Constrained scans

Declare the coordinate in `scan.inp`. This distance example uses one-based atom
indices and must be adapted to the actual system:

```text
$constrain
  force constant=0.5
  distance: 5, 12, auto
$scan
  mode=sequential
  1: 1.5, 3.2, 18
$end
```

`1:` refers to the first constraint; start, end, and steps share one line. Do not
repeat the atom indices there. The native inline form is also available:
`distance: 5, 12, auto; 1.5, 3.2, 18`.
Record target and actual coordinates, energies, and convergence for each point,
including scan direction and failures. A scan maximum is a candidate for further
saddle searching, not a validated transition state.

## Molecular dynamics

Use a `$md` block in `md.inp` to explicitly set temperature, duration, timestep,
and trajectory output interval. Check units and thermostat options against the
target version. Record starting geometry, velocities/random seed when supported,
and constraints. Inspect trajectories, temperature, energy drift, and integration
stability; a nonequilibrium trajectory alone does not establish an equilibrium
free energy or a reaction mechanism.

## Parser coverage

`scripts/parser.py::parse_xtb_artifacts` accepts `sp`, `opt`, `freq`, `opt_freq`,
and `md`, extracting SCC, energies, optimization, frequencies, and trajectory
summaries. Generic Jobs do not invoke it automatically; import it explicitly in
an analysis script and preserve its `_shared/xyz.py` dependency.
There is no scan parser branch: analyze frames in `xtbscan.log` alongside the raw
log and register the actual analysis outputs. Parsed fields are observations;
scientific conclusions require the raw evidence and task-specific criteria.
