# Gaussian TS/Frequency And IRC Validation

Use this when preparing, running, parsing, or judging Gaussian TS/Freq and IRC jobs.
For structured reaction-type, reaction-center, electronic, orbital, and energy
records, read `references/mechanism_analysis_sources.md` before finalizing the
node. When the Gaussian job refines a lower-level candidate, read
`references/refinement_ladder.md` before preparing the input.

## TS/Frequency Input

Use a candidate XYZ explicitly. For multi-frame XYZ/extXYZ, select a frame by
index or `first/last`; do not silently use an arbitrary frame.

Gaussian TS optimization is a refinement or validation step for a specific
candidate, not a default search method. The candidate may come from manual
construction, scan, NEB/string/GSM, dimer, QST, Gaussian-External-xTB, xTB/GFN,
semiempirical, or another documented lower-level search. Preserve the parent
candidate evidence and record what level/backend changed for the Gaussian
refinement branch.

Example:

```bash
python scripts/prepare_gaussian_ts_input.py candidate.xyz nodes/n230_gaussian_tsfreq/inputs/candidate_tsfreq.gjf \
  --route "#P UM062X/def2SVP EmpiricalDispersion=GD3 SCF=XQC Opt=(TS,CalcFC,NoEigen,MaxCycles=100) Freq NoSymm" \
  --charge -1 --multiplicity 2 \
  --nproc 32 --mem 64GB --chk candidate_tsfreq.chk
```

Use `.out` for new Gaussian outputs. Keep `.log` compatibility only for old artifacts.
For node-scoped inputs under `nodes/<node_id>/inputs`, use a bare
`%chk=<job>.chk` unless deliberately referencing another node. The bundled
runner executes Gaussian from `nodes/<node_id>/outputs`, so bare checkpoints,
stem-scoped driver logs, and stem-scoped run metadata stay in the node output
directory. For input `candidate.gjf`, job metadata is written as
`candidate.run_metadata.txt`, `candidate.g16_driver.out`,
`candidate.submit_receipt.txt`, and `candidate.runner.nohup`; legacy
`run_metadata.txt` / `g16_driver.out` names are read only for old artifacts and
are copied back into the stem-scoped local filename when used as a fallback.
Do not run Gaussian from the workspace root. By default the bundled runner uses
`nodes/<node_id>/scratch/gaussian` as `GAUSS_SCRDIR`; override `--scratch` only
when the alternate scratch path is node/job-unique.

For Gen/GenECP inputs, preflight the file before remote execution. Missing
element basis blocks, pseudo blocks, or malformed section boundaries should be
fixed in a new input file instead of silently submitted:

```bash
python scripts/gaussian_gen_preflight.py nodes/n230_gaussian_tsfreq/inputs/candidate_tsfreq.gjf \
  --fix \
  --output nodes/n230_gaussian_tsfreq/inputs/candidate_tsfreq.fixed.gjf
```

## Remote Execution

Use the bundled runner when possible. For long TS/Freq/IRC jobs, prefer
`--background`: it submits with nohup on the compute host and returns
immediately, so the job survives SSH disconnects instead of depending on a
blocked foreground session:

```bash
python scripts/run_remote_gaussian.py nodes/n230_gaussian_tsfreq/inputs/candidate_tsfreq.gjf \
  --login-host iaw.1w \
  --compute-host compute-0-30 \
  --remote-dir /home/iaw/codex_runs/<run_name>/tssearch_<system> \
  --background
```

When the input path is `nodes/<node_id>/inputs/*.gjf`, `--remote-dir` is treated
as the remote workspace root and the runner automatically uses
`nodes/<node_id>/outputs` as the remote run directory. Poll
`nodes/<node_id>/outputs/<input_stem>.run_metadata.txt` for an `end=` line,
then pull results with the same command plus `--fetch-only`. Short jobs can
omit `--background` to run in the foreground and download automatically.

For background jobs, use the node-scoped monitor wrappers instead of hand-written
nested SSH commands:

```bash
python scripts/ts_remote_status.py \
  --root /home/iaw/codex_runs/<run_name>/tssearch_<system> \
  --node n230_gaussian_tsfreq \
  --login-host iaw.1w \
  --compute-host compute-0-30

python scripts/ts_remote_tail.py \
  --root /home/iaw/codex_runs/<run_name>/tssearch_<system> \
  --node n230_gaussian_tsfreq \
  --login-host iaw.1w \
  --compute-host compute-0-30 \
  --file auto \
  --lines 80

python scripts/ts_remote_fetch.py \
  --root /home/iaw/codex_runs/<run_name>/tssearch_<system> \
  --node n230_gaussian_tsfreq \
  --login-host iaw.1w \
  --compute-host compute-0-30 \
  --local-root tssearch_<system>
```

These commands are read-only except for local fetch output. They inspect
`*.run_metadata.txt`, legacy `run_metadata*.txt`, `*.submit_receipt.txt`,
legacy `submit_receipt.txt`, PID files, runner logs, Gaussian outputs, and
driver logs under
`nodes/<node_id>/outputs`.

If Gaussian stdout redirection to the node `outputs/` directory is unreliable
on the shared filesystem, add `--scratch-stdout`. The runner writes Gaussian
stdout and driver stderr under `GAUSS_SCRDIR` first, then copies the completed
`.out` and `<input_stem>.g16_driver.out` back into node `outputs/`.

## Endpoint Optimization Continuations

Do not assume `Opt=(...,MaxCycles=N)` or `Opt=(...,MaxCycle=N)` changes the
ordinary Gaussian Opt step cap on every target build. Preserve the output and
parse it first. The parser reports `summary.opt_cycle_diagnostics`, including
the requested `MaxCycle(s)` value, the printed `Step number ... out of a maximum
of M` value, `NStep`, and warnings such as
`opt_maxcycle_request_mismatch` or `opt_step_limit_reached`.
`opt_step_limit_reached` is keyed to the printed Gaussian step line reaching
`N == M`; `NStep` is reported as a diagnostic but is not by itself proof that
the printed Opt maximum was reached.

When the printed maximum remains 100, prefer an explicit continuation branch:
extract the final geometry, write a new endpoint-optimization node, and record
the previous capped output as evidence. Internal Gaussian option overrides must
be opt-in and validated on the target Gaussian build before use.

Remote Gaussian jobs consume compute resources. Start them only after the user has authorized that compute work in the task context.

The Python remote runner is backed by `src/transition_state_workflow/remote/exec.py`
for SSH command construction and `src/transition_state_workflow/remote/job_runner.py`
for the engine-neutral job lifecycle. Local execution must stay argv-based
through `subprocess.run(..., shell=False)`. Operators such as `&&`, `>`,
`2>&1`, `< /dev/null`, `&`, and `$!` belong only inside the final compute-host
`bash -lc` command; do not hand-write nested SSH strings that let the login
host interpret those operators.

`run_remote_gaussian.py` is the Gaussian engine adapter over the generic remote
job lifecycle. It owns Gaussian-specific input placement, `.out`/driver log
names, checkpoint handling, and scratch copy-back behavior. xTB or ASE/NEB
remote execution should provide its own engine adapter and `RemoteJobSpec`
instead of passing non-Gaussian jobs through this CLI.

Runner scripts that source `g16.profile` under `set -euo pipefail` must disable
both `-e` and `-u` while sourcing, then restore strict mode:

```bash
set +e +u
source /home/iaw/soft/Gaussian/g16/bsd/g16.profile
profile_status=$?
set -e -u
```

Reusable templates live in `templates/`:

- `gaussian_profile_safe_runner.sh`: single-job strict-shell Gaussian runner.
- `gaussian_displacement_endpoint_parallel_runner.sh`: concurrent plus/minus
  displacement endpoint optimization runner with separate scratch directories,
  logs, PIDs, and exit-code collection.

## Parse And Validate

```bash
python scripts/parse_gaussian_ts_result.py candidate_tsfreq.out -o parsed_result --strict
```

Set `claim_status=tsfreq_validated` only if the selected Gaussian job section shows:

- normal termination;
- stationary point evidence;
- optimization convergence evidence;
- exactly one imaginary frequency;
- final geometry and energy are available.

For concatenated or Link1 logs, parse the intended job section only. Do not validate from unrelated later force tables.

## Imaginary Mode Judgment

Exactly one imaginary frequency is necessary but not sufficient. Inspect whether the displacement follows the intended reaction coordinate:

- forming/breaking bonds change in the expected direction;
- donor-H-acceptor motion is present for proton transfer;
- spin/charge migration is considered for HAT/PCET/open-shell cases;
- low-magnitude soft modes are not mistaken for reaction-center TSs.

Use the bundled node-scoped helper to extract the final TS geometry, plus/minus
mode displacements, and optional endpoint optimization inputs:

```bash
python scripts/ts_imaginary_mode_follow.py prepare nodes/n230_gaussian_tsfreq/outputs/candidate_tsfreq.out \
  --workspace tssearch_<system> \
  --node-id n240_imaginary_follow \
  --template-gjf nodes/n230_gaussian_tsfreq/inputs/candidate_tsfreq.gjf \
  --scale 0.25
```

In node-scoped mode the helper writes endpoint `.gjf` files under
`nodes/<node_id>/inputs`, structures and launch scripts under
`nodes/<node_id>/outputs`, and summaries under `nodes/<node_id>/parsed`. Generated
endpoint launch scripts run Gaussian with stdin/stdout redirection so endpoint
`.out` files stay in the node `outputs/` directory.

## Descriptor Extraction

After TS/Freq validation and imaginary-mode displacement are available, extract
a compact descriptor table into the node `parsed/` directory:

```bash
python scripts/ts_descriptor_extract.py \
  --ts-out nodes/n230_gaussian_tsfreq/outputs/candidate_tsfreq.out \
  --ts-xyz nodes/n240_imaginary_follow/outputs/ts_final.xyz \
  --minus-xyz nodes/n240_imaginary_follow/outputs/mode_minus.xyz \
  --plus-xyz nodes/n240_imaginary_follow/outputs/mode_plus.xyz \
  --pairs 4-12 7-15 \
  -o nodes/n240_imaginary_follow/parsed
```

Report orbital, APT charge, spin-density, or population descriptors as
unavailable when the Gaussian output does not contain the required sections.
Do not infer those values from filenames, route text, or related calculations.
If a descriptor changes the mechanism interpretation, attach it through
`finalize-node --mechanism-analysis` with the descriptor JSON or Gaussian output
as the cited source.

## IRC Follow-Up

Prepare separate forward and reverse jobs from the validated TS checkpoint or geometry:

```text
#P UM062X/def2SVP EmpiricalDispersion=GD3 SCF=XQC IRC=(CalcFC,Forward,MaxPoints=200,StepSize=2) NoSymm
#P UM062X/def2SVP EmpiricalDispersion=GD3 SCF=XQC IRC=(CalcFC,Reverse,MaxPoints=200,StepSize=2) NoSymm
```

If IRC fails with corrector convergence errors, preserve the failed log and retry with smaller `StepSize`. Do not interpret raw IRC last points as optimized minima.

## QST2 Internal-Coordinate Failure

For Gaussian errors such as `RedCar/ORedCr failed for GTrans`, l101 setup
failure, or immediate segmentation during redundant-internal QST2 setup:

- preserve the `.out` and close the branch as `claim_status=not_evaluated`,
  `outcome=numerical_failure`, with an `outcome_code` such as
  `gaussian_redcar_gtrans_failure`, `l101_qst2_setup_failure`, or
  `qst2_internal_coordinate_failure`;
- do not repeat the same default QST2 input unchanged;
- try `Opt=(QST2,Cartesian,...)` or another coordinate-stabilized variant if
  QST2 remains chemically justified;
- otherwise backtrack to the validated endpoint node and branch to scan, NEB,
  dimer, or another candidate-generation route.

## Failure Reflection

If Gaussian fails or gives the wrong TS:

- classify numerical failure separately from mechanism mismatch;
- compare final geometry to endpoint references;
- inspect imaginary mode, `<S^2>`, energy, and key bonds;
- decide whether to retry from the same candidate, branch to a new mechanism, or backtrack to endpoint definitions.
