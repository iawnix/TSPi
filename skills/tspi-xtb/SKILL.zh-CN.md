---
name: tspi-xtb
description: 在明确证据边界下使用 xTB 和 CREST 完成构象、几何、频率、扫描、分子动力学和预筛选任务。
---

# TSPi xTB 与 CREST

[English version](SKILL.md)

当任务涉及 xTB 或 CREST 计算时使用本 Skill。计算、产物和状态合同使用
`tspi-orchestration`；候选生成策略使用 `tspi-transition-state-search`。

xTB 是用于有边界探索和表征的近似执行器。CREST 通过基于 xTB 的搜索提供构象
集合。正常结束标记、低能量或优化几何都不能单独证明经典过渡态或反应机理。

## 操作规则

- 用逻辑 artifact 绑定 `xyz`；xTB 扫描和 MD 还要绑定 `control`。
- 将方法、电荷、未成对电子、溶剂模型、精度和优化级别写入科学意图，重试时
  不能静默改变。
- 检查完整输出集合和 parser summary，包括适用时的 SCC 收敛、优化状态、频率、
  扫描完整性或轨迹完整性。
- 将构象数量、能量表和集合几何作为独立事实；通过 Claim 或 Node 理由选择构象。
- 只有已核验的 parser 值和原始产物才能通过 `ts_change` 提升。

## 参考资料

- 执行器输入、设置和产物：`references/xtb_executor.md`
- CREST 集合检查：`references/crest_ensemble.md`
