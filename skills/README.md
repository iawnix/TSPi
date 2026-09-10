# TSPi Skills

TSPi is distributed as one Pi package with several independently discoverable
Skills. The package exposes the orchestration contract and specialized method
guidance as separate resources so a session can load only what its current
question needs.

| Skill | Responsibility | Load when |
| --- | --- | --- |
| `tspi-orchestration` | workspace state, Decisions, evidence, validation, subagents, operations, and recovery | any TSPi research task or state change |
| `tspi-transition-state-search` | candidate construction and TS search strategy | choosing QST, scans, NEB, conformers, branches, or recovery strategy |
| `tspi-xtb` | xTB and CREST setup and result interpretation | using xTB prescreening, optimization, frequencies, scans, MD, or conformers |
| `tspi-gaussian` | Gaussian input and output evidence | using Gaussian single-point, optimization, frequency, or IRC calculations |
| `tspi-qbics` | QBICS/DMECP electronic-state crossing calculations | studying crossings or non-adiabatic state character with QBICS |
| `tspi-connectivity` | endpoint assignment and molecular structure evidence | checking IRC connectivity, atom maps, stereochemistry, or basin identity |
| `tspi-render` | deterministic visual artifacts | rendering, comparing, animating, or presenting mechanisms |
| `tspi-report` | evidence-bound report packages | building a report from a validated workspace |
| `tspi-email` | fixed-target notification delivery | sending receipt-bound research updates |

Every Skill has an English `SKILL.md` and a Chinese `SKILL.zh-CN.md`. The
orchestration Skill owns cross-cutting contracts; focused Skills do not duplicate
those contracts or acquire permission to mutate canonical state.
