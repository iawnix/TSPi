---
name: tspi-mechanism
description: 使用显式原子映射、基元步骤 Finding 和能力目录研究反应机理与竞争路径。
---

# TSPi 反应机理

[English version](SKILL.md)

当问题涉及反应定义、原子映射、键变化、基元步骤、竞争路径或机理 Claim 时使用本
Skill。ResearchMap 由编排 Skill 管理；本 Skill 负责选择化学方法，并把核验过的分析
结果记录为 `FactFinding` 或 `IssueFinding`。

用 `ts_state mode=capabilities capabilityKind=analysis` 查看能力，再用
`<capability>@<version>` 查询输入角色。`ts_analyze` 使用角色到 Artifact ID 数组；
检查返回的产物和诊断，不猜能力名称，也不把分析返回直接当作 Claim 结论。

映射必须显式提供，或复用绑定于相同输入 Artifact 的映射。检查元素标签、一对一覆盖、
总元素计数和未映射原子。元素一致不等于化学身份；对称性、质子转移、片段配对、同位
素和电子态需要独立判断。核验过的映射值记录为 FactFinding，未决歧义和失败候选记录
为 IssueFinding，并引用来源 Artifact。

物种身份、基元步骤连通性、过渡态、热化学和动力学分开研究。竞争机理使用独立 Claim
和 Claim relation。化学网络可以有环路，但 ResearchNode 依赖图仍必须无环。

`ts_manage` 只暂停或恢复 Node 的运行派发，不改变 ResearchMap；科学状态使用
`ts_change` 的 `set_node_state`。方法细节见[反应映射](references/reaction_mapping.md)、
[分子准备](references/molecular_preparation.md)、[TS 证据](references/ts_evidence.md)和
[热化学与网络](references/energies_networks.md)。
