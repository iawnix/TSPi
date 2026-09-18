---
name: tspi-transition-state-search
description: 选择和评估 QST、扫描、NEB、构象搜索、分支与恢复等过渡态候选生成方法。
---

# TSPi 过渡态搜索

[English version](SKILL.md)

当问题是如何构造、探索或恢复过渡态候选时使用本 Skill。Node、Artifact、Finding、
Gate 和 ChangeSet 使用 `tspi-orchestration`；候选生成之后还要进行确认计算。

根据基元步骤假设、端点质量、原子映射、电子态、构象不确定性、成本和可用能力，在
QST、直接优化、弛豫扫描、NEB、片段构造和构象采样之间选择。每个候选问题使用一个
ResearchNode，以 Artifact ID 绑定输入；保留失败候选，若它影响决策就记录为
IssueFinding。假设或交付物改变时创建依赖 Node。

候选生成不等于验证。继续收集驻点、模式、连通性、电子态和稳健性 Finding。参考
[候选生成](references/candidate_generation.md)、[后端选择](references/backend_selection.md)、
[ASE NEB](references/ase_neb_executor.md)、[ASE NEB 中文](references/ase_neb_executor.zh-CN.md)、
[机理反思](references/mechanism_reflection.md)和[策略反思](references/strategy_reflection.md)。
