---
name: tspi-transition-state-search
description: Choose and assess transition-state candidate generation methods such as QST, scans, NEB, conformer search, branching, and recovery.
---

# TSPi Transition-State Search

[Chinese version](SKILL.zh-CN.md)

Use this Skill when the question is how to construct, explore, or recover a
transition-state candidate. Load `tspi-orchestration` for Nodes, Artifacts,
Findings, Gates, and ChangeSets. Candidate generation must be followed by the
calculations needed to establish the proposed transition state.

Choose QST, direct optimization, relaxed scans, NEB, fragment construction, or
conformer sampling from the elementary-step hypothesis, endpoint quality, atom
mapping, electronic state, uncertainty, cost, and available capabilities.
Give each candidate-generation question one ResearchNode, bind inputs by
Artifact ID, and preserve failed candidates as `IssueFinding` when they bound
the search or explain a decision. A changed hypothesis or deliverable starts a
dependent Node.

Candidate generation is not validation. Continue with stationary-point, mode,
connectivity, electronic-state, and robustness Findings appropriate to the
Claim. Read [candidate_generation.md](references/candidate_generation.md),
[backend_selection.md](references/backend_selection.md),
[ase_neb_executor.md](references/ase_neb_executor.md),
[ase_neb_executor.zh-CN.md](references/ase_neb_executor.zh-CN.md),
[mechanism_reflection.md](references/mechanism_reflection.md), and
[strategy_reflection.md](references/strategy_reflection.md).
