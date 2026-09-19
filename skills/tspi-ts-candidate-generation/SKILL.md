---
name: tspi-ts-candidate-generation
description: Generate transition-state candidate geometries with chemically informed construction, scans, QST, NEB, or conformer and orientation sampling.
---

# TSPi TS Candidate Generation

[Chinese version](SKILL.zh-CN.md)

Use this Skill to produce candidate geometries for a proposed elementary step.
Candidate generation does not establish a transition state; validation belongs
to `tspi-ts-validation`, and method or Backend choice belongs to
`tspi-method-selection`.

Start from explicit reactant/product identities, atom mapping, charge,
multiplicity, and relevant conformers. Choose chemically informed construction,
a relaxed scan, QST2/QST3, direct TS optimization, NEB, or fragment orientation
sampling according to the proposed bond changes and available evidence. Bind
all seeds and generated structures as Node-owned Artifacts and preserve the
method, constraints, frame selection, and provenance.

Do not promote a scan maximum, NEB image, interpolation, or constrained
structure as a verified saddle point. Record useful candidates as facts about
the generated structure and failed or distorted searches as issues only when
they inform the research question.

Read [candidate_generation.md](references/candidate_generation.md) for method
criteria. For the registered ASE/xTB NEB executor, read
[ase_neb_executor.md](references/ase_neb_executor.md) or
[ase_neb_executor.zh-CN.md](references/ase_neb_executor.zh-CN.md).
