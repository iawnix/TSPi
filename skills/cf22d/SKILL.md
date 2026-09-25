---
name: cf22d
description: Plan, diagnose, and run a registered PySCF CF22D single-structure workflow for SCF, optimization, transition-state, frequency, and RRHO thermochemistry tasks.
---

# TSPi CF22D

[Chinese version](SKILL.zh-CN.md)

Use this Skill for a bounded PySCF workflow whose density-functional method is
CF22D. The standalone `pyscf_runner` package is an input and execution helper;
it is not a TSPi Backend unless TSPi exposes a deterministic capability, input
roles, output roles, parser contract, and task-validation tests.

Before execution, read the artifact catalog and the live compute catalog:

```text
research.read mode=artifacts
research.read mode=capabilities capabilityKind=compute
```

Use only the exact capability and parameter schema returned by the catalog. If
no PySCF/CF22D capability is registered, provide method guidance and a doctor
plan only. Do not invent a capability name, construct a `compute.run` request for
an unavailable descriptor, invoke `pyscf-runner` through arbitrary shell, or
present a local smoke test as a TSPi calculation.

The current adapter uses version-1 IDs `pyscf.sp`, `pyscf.opt`, `pyscf.ts`,
`pyscf.freq`, `pyscf.thermo`, `pyscf.opt_freq`, and `pyscf.ts_freq` when they
are present in the live catalog. Treat that list as a routing hint, not a
substitute for catalog discovery or readiness.

Bind the source XYZ Artifact, task list, charge, PySCF spin (`2S`, not a
multiplicity), basis, CF22D method settings, optimization/TS settings,
frequency threshold, thermochemistry conditions, runtime resources, and output
policy in the immutable calculation intent. Run the read-only environment
doctor before the first run and after dependency, configuration, or environment
changes. For a remote target this is `TSPi --check-remote`; for a local target
use the installation or adapter runtime probe when one is exposed. Read
[cf22d_workflow.md](references/cf22d_workflow.md) for task
ordering, input/output records, and scientific checks. Read
[environment_doctor.md](references/environment_doctor.md) for local and remote
readiness checks.

The PySCF Backend must be bound in `compute.toml` to an operator-managed
interpreter that contains PySCF, geomeTRIC, `pyscf-dispersion`, and the TSPi
runner module. Local workers source the configured activation script; remote
Torque jobs source the remote activation script after staging only the input
basename. Missing or stale bindings fail preflight. Do not install packages or
fall back to the host Python from inside a calculation.

Do not silently substitute another `xc` functional. If a descriptor permits an
`xc` override, use this Skill only when the frozen intent records `CF22D`; route
another functional through method selection and its applicable execution Skill.

The source runner owns one-structure `sp`, `opt`, `ts`, `freq`, and `thermo`
tasks. A TSPi adapter may additionally expose composite `opt_freq` and
`ts_freq` capabilities; their descriptor and artifact manifest control the
actual request.
`opt` and `ts` are mutually exclusive; `freq` adds an implicit SCF and
`thermo` adds implicit SCF and frequency work. A TS-plus-thermo request is
`ts -> sp -> freq -> stationary-point count -> thermo`. It does not run an
IRC, NEB, reaction scan, endpoint optimization, or crossing-point search.

Normal termination, SCF convergence, and one imaginary frequency are separate
facts. The runner's stationary-point check counts significant imaginary
frequencies (default threshold `-20 cm^-1`) but does not inspect the mode vector
or establish endpoint identity. Send those questions to
`tspi-ts-validation`, `tspi-irc`, and `tspi-mechanism-reasoning`; send energy
and RRHO interpretation to `tspi-energetics`.

Treat the adapter's `memory_mb` (the source runner calls this
`max_memory_mb`) as a PySCF budget rather than an operating-system hard limit.
A configured scratch base may contain only runner-owned run subdirectories;
cleanup must never remove the base directory or unrelated files. Verify the
declared primary outputs before recording separate FactFindings or IssueFindings
through the Research Kernel. The standalone runner normally writes `run.log`,
`result.json`, task records, geometry, Hessian/frequency, and thermochemistry
files; a TSPi adapter may instead declare names such as `pyscf.out`,
`pyscf_result.json`, and `pyscf_*` JSON/XYZ artifacts. The live capability's
artifact manifest is authoritative. A failed or incomplete parser result is not
a chemical verdict.
