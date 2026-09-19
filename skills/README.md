# TSPi Skills

[English](README.md) | [简体中文](README.zh-CN.md)

TSPi provides 15 focused Skills. The Research Kernel Skill owns the canonical
ResearchMap contract; orchestration chooses the next bounded task; scientific
and delivery Skills handle one method or output concern without redefining
state.

| Skill | Responsibility |
| --- | --- |
| [tspi-research-kernel](tspi-research-kernel/SKILL.md) | ResearchMap reads, validation, Findings, Gates, and atomic changes |
| [tspi-orchestration](tspi-orchestration/SKILL.md) | Task planning, branches, recovery, review, and stopping |
| [tspi-ts-candidate-generation](tspi-ts-candidate-generation/SKILL.md) | TS candidate construction, scans, QST, NEB, and sampling |
| [tspi-ts-validation](tspi-ts-validation/SKILL.md) | Saddle, mode, structure, electronic-state, and stereochemical validation |
| [tspi-irc](tspi-irc/SKILL.md) | Bidirectional paths and endpoint identity |
| [tspi-energetics](tspi-energetics/SKILL.md) | Energies, thermal corrections, barriers, bounded kinetics, and profiles |
| [tspi-method-selection](tspi-method-selection/SKILL.md) | Scientific method, Backend capability, and compute environment selection |
| [tspi-xtb](tspi-xtb/SKILL.md) | Registered xTB calculations |
| [tspi-crest](tspi-crest/SKILL.md) | CREST conformer ensembles |
| [tspi-qbics](tspi-qbics/SKILL.md) | QBICS method guidance and live capability discovery |
| [tspi-gaussian](tspi-gaussian/SKILL.md) | Gaussian input, execution, parsing, and output checks |
| [tspi-report](tspi-report/SKILL.md) | Revision-bound research reports |
| [tspi-render](tspi-render/SKILL.md) | Molecular images, animations, comparisons, and scientific curves |
| [tspi-email](tspi-email/SKILL.md) | Configured notifications and report delivery |
| [tspi-mechanism-reasoning](tspi-mechanism-reasoning/SKILL.md) | Mechanism hypotheses, mappings, elementary steps, and alternatives |

A transition-state study may invoke several Skills, but each keeps its own
boundary: candidate generation creates a structure, TS validation establishes
saddle evidence, IRC assigns endpoints, and energetics compares corrected
quantities. Root records their verified outputs in the same ResearchMap through
the Kernel.

Each Skill has matching English and Chinese entrypoints. Detailed procedures
are linked from the relevant Skill. Shared terminology is in the
[glossary](tspi-research-kernel/references/glossary.md).
