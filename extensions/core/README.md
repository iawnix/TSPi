# TSPi Skills

[English](README.md) | [简体中文](README.zh-CN.md)

TSPi provides a domain-neutral Research Harness with focused Skills in the current computational-chemistry bundle. `orchestration` and `research-state` are the two Core System Skills: their summaries are always included in the system prompt and their full references are available to the Agent. Domain and delivery Skills live in their own extension directories. The Research State Skill owns the
canonical ResearchMap contract; orchestration chooses the next bounded task;
scientific and delivery Skills handle one method or output concern without
redefining state.

| Skill | Responsibility |
| --- | --- |
| [research-state](skills/research-state/SKILL.md) | ResearchMap reads, validation, Findings, Gates, and atomic changes |
| [orchestration](skills/orchestration/SKILL.md) | Task planning, branches, recovery, review, and stopping |
| [candidate-generation](../chemical/skills/candidate-generation/SKILL.md) | TS candidate construction, scans, QST, NEB, and sampling |
| [validation](../chemical/skills/validation/SKILL.md) | Saddle, mode, structure, electronic-state, and stereochemical validation |
| [irc](../chemical/skills/irc/SKILL.md) | Bidirectional paths and endpoint identity |
| [energetics](../chemical/skills/energetics/SKILL.md) | Energies, thermal corrections, barriers, bounded kinetics, and profiles |
| [method-selection](../chemical/skills/method-selection/SKILL.md) | Scientific method, Backend capability, and compute environment selection |
| [cf22d](../chemical/skills/cf22d/SKILL.md) | Registered PySCF/CF22D workflows and runtime readiness |
| [xtb](../chemical/skills/xtb/SKILL.md) | Registered xTB calculations |
| [crest](../chemical/skills/crest/SKILL.md) | CREST conformer ensembles |
| [qbics](../chemical/skills/qbics/SKILL.md) | QBICS method guidance and live capability discovery |
| [gaussian](../chemical/skills/gaussian/SKILL.md) | Gaussian input, execution, parsing, and output checks |
| [email](../email/SKILL.md) | Configured notifications and delivery |
| [mechanism-reasoning](../chemical/skills/mechanism-reasoning/SKILL.md) | Mechanism hypotheses, mappings, elementary steps, and alternatives |
| [chemical-input](../chemical/skills/chemical-input/SKILL.md) | Natural-language chemical names, structure candidates, and input confirmation |

The Harness can host Skills for chemistry, data analysis, simulation, or other
research domains. The bundled transition-state study Skills keep their own
boundaries: candidate generation creates a structure, TS validation establishes
saddle evidence, IRC assigns endpoints, and energetics compares corrected
quantities. Root records verified outputs in the same ResearchMap through the
Research State.

Each Skill has matching English and Chinese entrypoints. Every detailed
reference also has an English and Simplified Chinese version; each entrypoint
links only to references in the same language. Shared terminology is in the
[glossary](skills/research-state/references/glossary.md).

Core and domain Skills use the same manifest validation. Entrypoints, translated references and executable resources are digest-pinned; selecting external domain extensions retains core validation.
