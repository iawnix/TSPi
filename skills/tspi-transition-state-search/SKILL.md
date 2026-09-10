---
name: tspi-transition-state-search
description: Choose and assess transition-state candidate generation methods such as QST, scans, NEB, conformer search, branching, and recovery.
---

# TSPi Transition-State Search

[Chinese version](SKILL.zh-CN.md)

Use this Skill when the research question is how to construct, explore, or
recover a transition-state candidate. Load `tspi-orchestration` for workspace
and evidence contracts. A generated structure is a candidate, not a proven
transition state.

## Method Choice

Choose a method from the elementary-step hypothesis, endpoint quality, atom
mapping, electronic state, conformational uncertainty, system size, cost, and
available executors. QST/QST2/QST3, direct TS optimization, relaxed scans, NEB,
fragment construction, and conformer sampling answer different candidate
generation problems. Do not impose a universal sequence or let the capability
catalog choose scientific strategy.

## Research Boundary

Give each candidate-generation question one ResearchNode and bind inputs by
logical artifact IDs. Record the method, assumptions, parameters, and intended
discriminator. Preserve failed candidates and method changes; a changed
hypothesis or deliverable starts a dependent Node. Candidate generation still
requires stationary-point, mode, connectivity, state, and robustness evidence
appropriate to the Claim.

## Focused References

- Candidate construction and follow-up evidence: `references/candidate_generation.md`
- Backend choice: `references/backend_selection.md`
- Mechanism Claim reflection: `references/mechanism_reflection.md`
- Repeated-result and failed-search reflection: `references/strategy_reflection.md`
