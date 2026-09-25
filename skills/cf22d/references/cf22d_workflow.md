# CF22D Workflow

This reference describes the source runner's contract. It does not create a
TSPi capability or authorize a direct process launch.

## Contents

- [Input Contract](#input-contract)
- [Task Graph](#task-graph)
- [Outputs And Verification](#outputs-and-verification)
- [Scientific Boundary](#scientific-boundary)

## Input Contract

The source runner accepts YAML or JSON through `pyscf-runner input.yaml` or
`python -m pyscf_runner input.yaml`. Its Python API is:

```python
from pyscf_runner import PySCFRunner, WorkflowConfig

result = PySCFRunner(config).run(["sp", "freq"])
```

The required molecule field is `molecule.xyz_file`. Preserve these intent
fields even when defaults are used:

- `molecule`: XYZ path, `basis` (default `def2-tzvp`), `charge`, `spin` as
  PySCF `2S`, `unit`, and verbosity;
- `method`: `xc: CF22D`, grid level (default `6`), SCF `conv_tol` (default
  `1e-10`), maximum cycles (default `400`), and optional checkpoint;
- `optimization` or `ts`: convergence thresholds, maximum steps, and whether
  to use an initial Hessian;
- `frequency`: normal-mode output and `imaginary_threshold_cm` (default
  `-20.0`);
- `thermo`: temperature and pressure for RRHO corrections;
- `runtime`: source `max_memory_mb` (the TSPi descriptor calls it `memory_mb`),
  `num_threads`, scratch policy, extra environment,
  resource recording, and `raise_on_error`;
- `output`: result directory/prefix, overwrite policy, snapshots, checkpoint,
  Hessian, frequencies, and thermochemistry files.

These are the standalone runner defaults. A TSPi adapter may deliberately
choose different bounded defaults (for example, a lower grid level or fewer
SCF cycles); treat its live capability descriptor and frozen calculation intent
as authoritative and record the effective values.

The adapter follows the source default of enabling an initial Hessian for
`ts` and `ts_freq`; an intent may explicitly disable it.

Do not silently change charge, spin, basis, method, or task order while
repairing an input. A changed scientific binding requires a new calculation
intent and, when it answers the same Node question, an explicit recalculation.

## Task Graph

The standalone runner supports `sp`, `opt`, `ts`, `freq`, and `thermo`. The
current TSPi adapter maps those tasks to version-1 capability IDs
`pyscf.sp`, `pyscf.opt`, `pyscf.ts`, `pyscf.freq`, and `pyscf.thermo`, and also
offers `pyscf.opt_freq` and `pyscf.ts_freq` composite descriptors. Use the
live catalog's version and schema; do not pass a source YAML task list as a
`compute.run` capability name.

- `opt` and `ts` cannot be requested together.
- `freq` requires an SCF on the current geometry; the SCF is implicit when
  `sp` was not requested.
- `thermo` requires both SCF and frequency; those tasks are implicit when they
  were not requested.
- `ts` changes the geometry before downstream SCF/frequency work. A combined
  TS and thermochemistry run is `TS -> SP -> FREQ -> TS validation -> THERMO`.
- `thermo` alone does not optimize a minimum or transition state.
- `opt_freq` and `ts_freq` combine geometry and frequency work in one adapter
  task; they do not add IRC or endpoint evidence.

The runner records implicit tasks separately. Keep requested and implicit work
distinct when summarizing provenance.

## Outputs And Verification

A successful or failed standalone run should preserve a run directory containing
the log, resolved configuration, original input snapshot, top-level JSON result,
task JSON records, and any enabled checkpoint, optimized/TS geometry, Hessian,
frequency, and thermochemistry files. A TSPi adapter may expose those results as
declared artifacts such as `pyscf.out`, `pyscf_result.json`,
`pyscf_geometry.xyz`, `pyscf_frequencies.json`, `pyscf_hessian.npy`, and
`pyscf_thermo.json`; the live capability descriptor and artifact manifest are
authoritative rather than a filename guessed from this reference. Resource
records may include requested threads, effective PySCF threads, memory budget,
wall/CPU time, and RSS snapshots. RSS is a process snapshot, not an exclusive
per-task measurement.

Current adapter descriptors use parser contract `pyscf.output/1`; still verify
the parser value returned by the live catalog and bind it in the calculation
intent. A parser name alone does not prove that required artifacts or task
validation facts are present.

Verify, in order:

1. The output belongs to the bound input digest and calculation intent.
2. The program reached its expected terminus and SCF convergence is present.
3. Required task outputs exist and are internally consistent.
4. The runner's task validation is read as operational evidence, not as a
   mechanism Claim.

With `raise_on_error: false`, failed tasks remain in task JSON and
`result.json`. Preserve the error class, message, and traceback when present;
do not replace them with an empty result or retry with changed parameters.

## Scientific Boundary

The built-in TS validation checks only the count of frequencies below the
configured threshold: zero for a minimum candidate and exactly one for a
first-order saddle candidate. It does not verify the imaginary-mode displacement,
atom mapping, stereochemistry, endpoint basins, or an IRC. It also does not
prove that CF22D is appropriate for a multireference, spin-crossing, metallic,
or strongly correlated problem.

The workflow is single-structure. IRC, NEB, reaction scans, endpoint identity,
crossing-point/DMECP searches, conformer ensembles, isotope corrections, and
microkinetics are outside this runner. Use the relevant TSPi Skill and a live
registered capability instead of extending a CF22D result implicitly.
