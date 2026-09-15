---
name: tspi-xtb
description: 运行和解释 xTB 与 CREST 的构象、几何、频率、扫描、分子动力学和预筛选计算。
---

# TSPi xTB 与 CREST

[English version](SKILL.md)

当任务涉及 xTB 或 CREST 计算时使用本 Skill。计算、产物和状态合同使用
`tspi-orchestration`；候选生成策略使用 `tspi-transition-state-search`。

xTB 提供用于探索和表征的近似电子结构计算。CREST 通过基于 xTB 的搜索提供构象
集合。评估过渡态和机理 Claim 时，使用所选理论水平下的驻点、模式和连通性证据。

## 操作规则

- 用逻辑 artifact 绑定 `xyz`；xTB 扫描和 MD 还要绑定 `control`。
- 将方法、电荷、未成对电子、溶剂模型、精度和优化级别写入科学意图；调整这些
  设置时，更新意图并记录为重新计算。
- 检查完整输出集合和 parser summary，包括适用时的 SCC 收敛、优化状态、频率、
  扫描完整性或轨迹完整性。
- 远程提交 xTB 或 CREST 前，要求已配置的软件 profile 通过 `ts_remote doctor`。
  命令、激活脚本或运行时依赖缺失属于运维失败；不得从计算作业中安装或修复集群软件。
- 将构象数量、能量表和集合几何作为独立事实；通过 Claim 或 Node 理由选择构象。
- 只有已核验的 parser 值和原始产物才能通过 `ts_change` 提升。

## 参考资料

- 执行器输入、设置和产物：[xtb_executor.md](references/xtb_executor.md)
- CREST 集合检查：[crest_ensemble.md](references/crest_ensemble.md)
