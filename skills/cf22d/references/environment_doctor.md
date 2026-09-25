# CF22D Environment Doctor

The doctor is a read-only readiness probe. It must not submit a calculation,
alter ResearchMap state, install packages into an installation-owned runtime,
or clean files outside a runner-owned scratch subdirectory.

## Contents

- [When To Run](#when-to-run)
- [Checks](#checks)
- [Readiness And Recovery](#readiness-and-recovery)
- [Capability Boundary](#capability-boundary)

## When To Run

Run the doctor before the first CF22D calculation, after changing the selected
local/remote environment or `compute.toml`, and after changing the managed
Python release or native libraries. A successful previous run is not evidence
that a different environment or capability is ready.

For a remote target, use the installation's read-only environment diagnostic
(`TSPi --check-remote`). Use `compute.environment` to inspect the configured
environment and its Backend bindings; do not substitute an ad-hoc SSH command.
The existing remote contract checks connection, scheduler, writable remote root,
queues/nodes, activation, and each registered backend; remote readiness is still
checked again during calculation preflight. `TSPi --check-remote` is remote-only.
For a local target, use an installation or adapter runtime probe when exposed;
otherwise treat calculation preflight as the readiness gate and do not claim a
separate local doctor exists.

## Checks

The PySCF/CF22D adapter's doctor should report each check separately, with
version/origin where available:

1. The selected interpreter and `pyscf-runner` entry point or module resolve
   from the installation-owned runtime.
2. `import pyscf`, `geometric`, `numpy`, `yaml` (PyYAML), `psutil`, and the
   PySCF dispersion module succeed. Record module origins; do not accept an
   accidental user-site import.
3. PySCF can construct the requested DFT object with `xc="CF22D"` and the
   configured basis/charge/spin on a tiny probe molecule. Construction must be
   a bounded probe and must not be reported as a scientific result.
4. The configured grid level, SCF tolerance, and cycle limit are accepted;
   the probe need not run a production optimization or frequency calculation.
5. The selected scratch base is writable, and a unique child can be created
   and removed without touching the base or another run.
6. Requested thread count, PySCF memory budget, and scheduler resource limits
   are representable. The adapter's `memory_mb` (source name `max_memory_mb`)
   is a PySCF budget, not an OS hard limit;
   leave scheduler and interpreter headroom.
7. Output and checkpoint destinations are writable and do not overwrite an
   existing Artifact without an explicit intent.

If the adapter supports remote execution, run the same dependency/probe checks
inside the configured activation and Python environment. A command being on
`PATH` is not enough; the import origins and CF22D construction must match the
selected environment.

## Readiness And Recovery

Return a structured result with `ok`, environment identity, interpreter and
module versions/origins, scratch/output checks, and bounded error messages. A
missing package, failed CF22D construction, unwritable path, or exceeded
resource ceiling is `not_ready`; it is not a failed scientific calculation.

Repair the installation-managed runtime or environment configuration, then rerun
the doctor. Do not pip-install into a shared hash-addressed runtime from inside
the research task, change `compute.toml` to bypass limits, or retry a calculation
whose intent has changed. Preserve the doctor record with the calculation plan
when reporting why execution was withheld.

## Capability Boundary

The doctor proves runtime readiness only. It does not register a capability,
choose a method, validate a transition state, or establish a reaction mechanism.
Descriptor presence in `research.read mode=capabilities capabilityKind=compute` also
does not prove that the selected local/remote environment is healthy.

When a TSPi adapter has not published exact input/output roles, parser, and
task-validation contracts, use the doctor for diagnosis only. Do not invent
public IDs for the source tasks `sp`, `opt`, `ts`, `freq`, or `thermo`; use only
the versioned names returned by the live catalog. Even after those single-
structure capabilities are registered, the source runner has no public IRC,
NEB, crossing-point, endpoint, or multi-structure capability.
