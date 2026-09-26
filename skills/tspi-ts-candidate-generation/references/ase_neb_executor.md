# ASE NEB Executor

The registered capability is `ase.neb@1`. It accepts exactly one `reactant` and
one `product` XYZ artifact. Each endpoint must contain one frame, and both files
must use the same atoms in the same order. The backend rejects identical or
rigidly equivalent endpoint geometries before preparation.

ASE provides NEB interpolation and path optimization. The default xTB CLI
calculator supplies energy and Cartesian gradients for every image. Set
`calculator = "gaussian_cli"` to use the configured Gaussian executable for
per-image `Force` jobs instead. Gaussian mode requires `gaussian_route`,
`gaussian_multiplicity`, `gaussian_nproc`, and `gaussian_mem`; the route is
forced to include Gaussian's `Force` keyword so ASE receives Cartesian
gradients. Supported electronic methods are `gfn1` and `gfn2` for xTB mode.
The managed runner evaluates images serially and uses no ASE preconditioner;
parallel image execution and `precon` are intentionally outside this capability.
The capability catalog is authoritative for parameter types and bounds. Main
parameters are `calculator`, `images`, `fmax`, `max_steps`, `spring_constant`,
`interpolation`, `neb_method`, `optimizer`, `climb`, `ci_neb`, `ci_fmax`,
`remove_rotation_and_translation`, `method`, `charge`, `uhf`, `accuracy`,
`electronic_temperature`, `solvent_model`, `solvent`, `gaussian_route`,
`gaussian_multiplicity`, `gaussian_nproc`, and `gaussian_mem`.

`neb_method` selects the ASE path formulation: `aseneb`, `improvedtangent`,
`eb`, `spline`, or `string`. `optimizer` selects the ASE optimizer:
`FIRE`, `BFGS`, `LBFGS`, or `MDMin`. Defaults are explicit in the prepared
command and echoed in `neb_summary.json`; the runner never relies on an ASE
version default.

The endpoints are input structures bound by the calculation intent;
`ase.neb@1` does not pre-optimize them automatically. To relax endpoints first,
run a registered optimization capability and bind its resulting XYZ artifacts
to a new NEB intent. This capability also does not accept a `transition_state`
input or discover one implicitly. TS-guided interpolation therefore requires a
pre-existing TS candidate and an explicit future input-role extension.

`ci_neb` is opt-in. When enabled, the runner first converges ordinary NEB with
`climb=false`, then starts a second stage with the climbing image and
`ci_fmax` (or `fmax` when omitted). If ordinary NEB does not converge, the CI
stage is not started. The summary records the effective settings, stage-level
convergence, and a bounded per-step history under `stages` and `history`; these
fields are additive, so older summaries remain readable.
`ci_fmax` is valid only when `ci_neb=true`; ordinary NEB and legacy single-stage
`climb` runs report it as `null` because no CI stage is executed.
The legacy single-stage `climb` mode and `ci_neb` are mutually exclusive; the
intent must choose one explicitly.
History records image energies and the maximum NEB force, not per-step image
coordinates. `neb.traj` and `neb_path.xyz` contain only the final band.

The required output set is:

- `ase_neb.out`: optimizer log and the runner completion marker, captured by
  the calculation worker from stdout;
- `neb.traj`: ASE-readable final image path;
- `neb_path.xyz`: portable final path with one energy per image;
- `neb_summary.json`: versioned run facts and convergence metrics.

The capability exposes these logical output roles as `program_output`,
`reaction_path`, `trajectory`, and `run_summary`; the bounded process history is
part of `neb_summary.json` rather than a second uncontrolled log artifact.

Parsing cross-checks the summary against the portable path, bound endpoints,
energy list, image and atom counts, and all required files. A completed Python
process is reported separately from task completion. `converged=false`, a
maximum NEB force above the final stage's `fmax` (or `ci_fmax`), mismatched
endpoints, or incomplete path data
leaves `task_validation.status=incomplete` even when the program terminated
normally.

## Runtime Readiness

The remote environment's `ase_neb` Backend binding must select the Python interpreter from
an operator-managed, versioned environment. That interpreter must import ASE,
NumPy, and the `ts_agent.backends.ase_neb_runner` version matching the TSPi
release that prepared the calculation. Set `TS_ASE_NEB_XTB` in the Backend
binding's environment variables to the validated xTB executable for xTB mode,
or `TS_ASE_NEB_GAUSSIAN` for Gaussian mode; do not depend on an interactive
shell's `PATH`.

Run `TSPi --check-remote` after deployment or environment changes and before the first
NEB submission. A missing interpreter, failed import, mismatched runner, or
failed probe for the selected calculator is an operational failure, not evidence
about the reaction path. Do not install packages from a calculation job or into
a research workspace. Follow the
[remote compute configuration](../../../docs/INSTALLATION.md#configure-remote-execution-compute-backends)
and switch the Backend binding only after its login-host and compute-node smoke
checks pass.
