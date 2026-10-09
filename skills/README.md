# Skill catalog and loading language

[English](README.md) | [简体中文](README.zh-CN.md)

**English `SKILL.md` is the default entrypoint.** Pi discovers names, descriptions,
and paths; the Agent reads bodies and references on demand. `SKILL.zh-CN.md` is
a Chinese translation, not an automatic locale switch or duplicate skill.
The Agent can explicitly read it when needed and respond or write reports in
the user's requested language. See [Skills and the execution catalog](../docs/EXTENSIONS.md)
for implementation and resource maintenance.

Skills guide methods using bundled helpers or task-specific inputs and scripts.
Convenience entries in `execution.json` do not set a capability ceiling.

| Skill | Purpose |
| --- | --- |
| [email](email/SKILL.md) | Prepare and send user-requested research email through configured SMTP or ClawEmail, with durable delivery receipts. |
| [research-memory](research-memory/SKILL.md) | Resume research through persistent problem Nodes, explicit relations, execution observations and immutable Results. |
| [research-workflow](research-workflow/SKILL.md) | Coordinate research problems, domain Skills, durable Jobs, materials and evidence-based Results through the native Pi loop. |
| [candidate-generation](../domains/chemical/skills/candidate-generation/SKILL.md) | Generate transition-state candidate geometries with chemically informed construction, scans, QST, NEB, or conformer and orientation sampling. |
| [cf22d](../domains/chemical/skills/cf22d/SKILL.md) | Run and interpret PySCF CF22D single-point, geometry optimization, transition-state, frequency, and RRHO thermochemistry calculations. |
| [chemical-input](../domains/chemical/skills/chemical-input/SKILL.md) | Resolve chemical names, inspect molecular graphs, generate reproducible initial geometries, and validate explicit reaction mappings with executable helpers. |
| [crest](../domains/chemical/skills/crest/SKILL.md) | Run and assess CREST conformer searches and preserve ensemble membership, energies, settings, provenance, and selection rationale. |
| [energetics](../domains/chemical/skills/energetics/SKILL.md) | Evaluate electronic energies, ZPE and thermal corrections, free and reaction energies, barriers, bounded TST rates, and energy profiles. |
| [gaussian](../domains/chemical/skills/gaussian/SKILL.md) | Prepare, run, and inspect Gaussian calculations, including single-point, optimization, frequency, transition-state, IRC, QST, and explicit scan inputs. |
| [irc](../domains/chemical/skills/irc/SKILL.md) | Plan and assess bidirectional intrinsic reaction coordinate calculations and assign their endpoints to declared molecular basins. |
| [mechanism-reasoning](../domains/chemical/skills/mechanism-reasoning/SKILL.md) | Form, compare, and revise reaction-mechanism hypotheses using explicit species identities, atom mappings, elementary steps, alternatives, and falsifiers. |
| [method-selection](../domains/chemical/skills/method-selection/SKILL.md) | Prepare a scientific method and named compute environment for execution, including when the user has already fixed the method. |
| [qbics](../domains/chemical/skills/qbics/SKILL.md) | Assess QBICS applicability and verify an installed command, its inputs and validation needs before running a bounded research Job. |
| [report](../domains/chemical/skills/report/SKILL.md) | Write illustrated research reports from evidence, with molecular structures, energy plots, data tables, methods, conclusions, and traceable sources. |
| [validation](../domains/chemical/skills/validation/SKILL.md) | Validate a transition-state candidate as a saddle point with the intended mode, structure, electronic state, and stereochemical assignment. |
| [xtb](../domains/chemical/skills/xtb/SKILL.md) | Use xTB for inexpensive structure screening, single points, optimization, frequencies, constrained scans, and molecular dynamics; interpret the raw outputs. |
