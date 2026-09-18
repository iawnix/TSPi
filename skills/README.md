# TSPi Skills

[English](README.md) | [简体中文](README.zh-CN.md)

TSPi includes nine Skills for planning research, running calculations, checking
results, and preparing figures and reports. The orchestration Skill manages
the research workflow; load a focused Skill when its method or output is needed.

| Skill | Use it for |
| --- | --- |
| [tspi-orchestration](tspi-orchestration/SKILL.md) | ResearchMap questions, Findings, Gates, and recovery |
| [tspi-transition-state-search](tspi-transition-state-search/SKILL.md) | Candidate construction, QST, scans, NEB, conformers, and search strategy |
| [tspi-xtb](tspi-xtb/SKILL.md) | xTB calculations and CREST conformer searches |
| [tspi-gaussian](tspi-gaussian/SKILL.md) | Gaussian inputs, optimization, frequencies, and IRC |
| [tspi-connectivity](tspi-connectivity/SKILL.md) | IRC endpoints, atom mapping, stereochemistry, and structure comparison |
| [tspi-mechanism](tspi-mechanism/SKILL.md) | Reaction definitions, explicit atom mappings, elementary steps, and mechanism comparisons |
| [tspi-render](tspi-render/SKILL.md) | Molecular images, animations, comparison panels, and scientific curves |
| [tspi-report](tspi-report/SKILL.md) | Research reports with evidence, calculation history, and figures |
| [tspi-email](tspi-email/SKILL.md) | Configured research notifications and report delivery |

For example, a Gaussian transition-state study uses orchestration to organize
the question and Node, transition-state search to choose a strategy, Gaussian
and connectivity to produce Findings, and render/report to present them.
Initial structures from SMILES and input imports are covered in
[artifact tools](tspi-orchestration/references/artifact_tools.md).

Each Skill has matching English and Chinese entrypoints. Detailed tool fields
and method references are linked from the relevant Skill; shared terminology
is in the [glossary](tspi-orchestration/references/glossary.md).
