---
name: tspi-xtb
description: 运行和解释 xTB 与 CREST 的构象、几何、频率、扫描、分子动力学和预筛选计算。
---

# TSPi xTB 与 CREST

[English version](SKILL.md)

当任务涉及 xTB 或 CREST 时使用本 Skill。计算、Artifact 和 ResearchMap 合同使用
`tspi-orchestration`；候选生成策略使用 `tspi-transition-state-search`。

用逻辑 Artifact 绑定 `xyz`，扫描或 MD 还要绑定 `control`。在计算意图中记录方法、电荷、
未成对电子、溶剂、精度和优化级别。检查 SCC 收敛、优化状态、频率、扫描和轨迹完整性。
构象数量、能量表和集合几何分别作为事实处理；核验值记录为 `FactFinding`，影响结论的
缺失输出、失败或方法限制记录为 `IssueFinding`。

远端任务使用 `ts_environment` 或 `/compute` 选择环境；命令或激活脚本缺失属于运行失败，
不要在计算作业中安装软件。详见 [xTB 执行器](references/xtb_executor.md) 和
[CREST 集合](references/crest_ensemble.md)。
