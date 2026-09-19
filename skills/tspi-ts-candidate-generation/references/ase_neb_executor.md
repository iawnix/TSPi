# ASE NEB Executor

The registered capability is `ase.neb@1`. It accepts exactly one `reactant` and
one `product` XYZ artifact. Each endpoint must contain one frame, and both files
must use the same atoms in the same order. The backend rejects identical
endpoint coordinates before preparation.

ASE provides NEB interpolation and FIRE optimization. A fixed xTB CLI
calculator supplies energy and Cartesian gradients for every image. Supported
electronic methods are `gfn1` and `gfn2`; no calculator substitution occurs.
The capability catalog is authoritative for parameter types and bounds. Main
parameters are `images`, `fmax`, `max_steps`, `spring_constant`,
`interpolation`, `climb`, `remove_rotation_and_translation`, `method`,
`charge`, `uhf`, `accuracy`, `electronic_temperature`, `solvent_model`, and
`solvent`.

The required output set is:

- `ase_neb.out`: optimizer log and the runner completion marker;
- `neb.traj`: ASE-readable final image path;
- `neb_path.xyz`: portable final path with one energy per image;
- `neb_summary.json`: versioned run facts and convergence metrics.

Parsing cross-checks the summary against the portable path, bound endpoints,
energy list, image and atom counts, and all required files. A completed Python
process is reported separately from task completion. `converged=false`, a
maximum NEB force above `fmax`, mismatched endpoints, or incomplete path data
leaves `task_validation.status=incomplete` even when the program terminated
normally.

## Runtime Readiness

The remote environment's `ase_neb` Backend binding must select the Python interpreter from
an operator-managed, versioned environment. That interpreter must import ASE,
NumPy, and the `ts_agent.backends.ase_neb_runner` version matching the TSPi
release that prepared the calculation. Set `TS_ASE_NEB_XTB` in the Backend
binding's environment variables to the validated xTB executable; do not depend on an interactive
shell's `PATH`.

Run `TSPi --check-remote` after deployment or environment changes and before the first
NEB submission. A missing interpreter, failed import, mismatched runner, or
failed xTB probe is an operational failure, not evidence about the reaction
path. Do not install packages from a calculation job or into a research
workspace. Follow the
[ASE NEB deployment procedure](../../../docs/INSTALLATION.md#deploy-the-ase-neb-runtime-with-pixi)
and switch the Backend binding only after its login-host and compute-node smoke
checks pass.
