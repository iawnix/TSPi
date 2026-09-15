---
name: tspi-mechanism
description: 使用显式原子映射、基元步骤证据和可组合能力研究反应机理与竞争路径。
---

# TSPi 反应机理

[English version](SKILL.md)

能力索引用 `ts_state mode=capabilities capabilityKind=analysis`；详情用
`query=<capability>@1`，不要猜参数。`ts_analyze.inputArtifacts` 是角色到 artifact
ID 数组的对象；从参数解析反应时传 `{}`。不同证据起点可以独立调用能力。

生成的 artifact 和 Activity 已自动记账。只有科学陈述需要引用时才提升事实；
单纯准备输入不需要新增 Observation。登记返回事实优先使用 `candidate_refs`，
由系统展开值、类型、单位和来源。通过
`ts_state mode=change_contract operation=record_observation` 查询两种变体。
同一 Decision 引用新分配的对象使用 `$<local_ref>`；`complete_node` 等操作引用
已有 Node，不分配新的 `local_ref`。

按问题读取：[反应与结构准备](references/molecular_preparation.md)、
[TS/模式/IRC 证据](references/ts_evidence.md)、
[热化学、动力学与网络](references/energies_networks.md)。

使用 `ts_manage operation=pause|resume nodeId=<id> rationale=<reason>` 暂缓或恢复
开放 Node 的后续计算/分析派发。在途 Attempt 仍通过 `ts_calc` 查看、收集或精确
取消；这不改变科学状态。终态 Node 通过新依赖节点继续研究。
当问题涉及反应定义、原子映射、键变化、基元步骤、竞争路径或机理 Claim
时使用本 Skill。使用 `tspi-orchestration` 处理 Node、artifact、Observation
和 Decision 合同；端点身份和立体化学使用 `tspi-connectivity`；具体计算方法
使用当前选择的方法 Skill。

根据能力目录和已有证据选择能力。本 Skill 不规定计算顺序。映射验证可以单独
作为一个 Node，多个 Node 的证据可以共同支持一个 Claim，失败候选也可以作为
研究边界保留。

## 映射规则

- 分析依赖原子对应关系时，提供显式映射，或复用绑定于相同输入 artifact 的已验证映射。
- 使用 `ts_state mode=capabilities capabilityKind=analysis` 查看
  `reaction.mapping.validate` 及其限制。
- 使用 `ts_analyze` 传入已注册的反应物/产物 artifact 和映射。它验证元素标签、
  一对一覆盖、全反应元素计数和未映射原子，不自动生成映射。
- 元素一致和覆盖完整本身不能证明化学身份。对结论有影响的对称原子、质子转移、
  片段配对、同位素和电子态问题需要独立判断，未决证据按已有 Finding 合同记录。
- 检查返回的分析 artifact，并通过 `ts_change` 将选定事实提升为 Observation；
  分析结果本身不是 Claim 判定。

## 机理规则

- 将物种身份、基元步骤连通性、TS 证据、热化学和动力学作为不同问题处理。
- 竞争机理使用独立 Claim，并用 ClaimRelation 表达替代或冲突。不能从一个接受的
  TS 或图中的一条路径直接推断主导机理。
- 化学反应网络可以有计量型多反应物边、可逆步骤和环路；研究 Node DAG 的无环
  规则不适用于化学网络。
- 每个能量或速率比较都记录条件、标准态、电荷/电子态、溶剂/环境和方法。

当前能力合同和有限示例见[反应映射参考](references/reaction_mapping.md)。多步
结论另读 `tspi-orchestration` 的路径模型和 `tspi-report` 的报告合同。
