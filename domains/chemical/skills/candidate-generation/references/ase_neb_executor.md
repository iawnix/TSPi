# ASE NEB availability

The current package does not provide a registered ASE NEB workflow or a bundled
NEB runner. The former `ase.neb@1` interface is not a callable capability.
Installing ASE or finding xTB/Gaussian alone does not establish an executable NEB path.

If the selected environment supplies a documented NEB script, inspect its actual
input and output contract, calculator bindings and dependencies before using it
through `job_start`. Otherwise implement and verify a bounded runner, or choose
an available candidate-generation method that preserves the scientific goal.
A missing local Skill script does not prove that shared runners or external tools
are unavailable. Record a concrete blocker only after checking those routes.

NEB needs atom-mapped endpoints with consistent atom order, charge and electronic
state. Record endpoint relaxation, interpolation, image count, optimizer,
force threshold, calculator settings and climbing-image policy explicitly.
Preserve the path, per-image energies and convergence evidence. A highest-energy
image is a candidate, not a validated transition state.

For existing execution paths, consult the [Gaussian Skill](../../gaussian/SKILL.md)
for explicit TS/scan/QST inputs and [chemical-input](../../chemical-input/SKILL.md)
for molecular seed preparation. The [mapped DA path](gaussian_path.md) supplies bounded QST2/IRC preparation; no automatic NEB implementation is provided.
