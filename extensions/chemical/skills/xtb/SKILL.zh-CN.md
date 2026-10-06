---
name: xtb
description: 运行和评估已注册的 xTB 单点、优化、频率、扫描、分子动力学与预筛计算。
---

# TSPi xTB

[English version](SKILL.md)

使用本 Skill 处理已注册的 xTB workflow。CREST 构象搜索由 `crest` 负责；是否
选择 xTB 而非其他方法由 `method-selection` 负责。

将 XYZ 以及扫描或分子动力学所需的 control 输入绑定为逻辑 Artifact。在 calculation
intent 中明确方法、电荷、未成对电子数、溶剂模型、精度、优化设置与约束。按任务检查
SCC 收敛、优化状态、频率数据、扫描完整性和轨迹完整性。

优化几何、能量、频率集合、扫描序列与轨迹是不同结果。记录 Finding 前检查原始输出。
扫描极大值或 xTB 虚频只能提供后续验证的候选，不能证明其为过渡态。详见
[xtb_executor.zh-CN.md](references/xtb_executor.zh-CN.md)。优化后继续单点计算时，必须使用
结果中的 `calculation.optimized_geometry_artifact_id`，并确认 Artifact 类型为
`chemical/xyz`；不能按 `artifact_ids` 的位置选择 stdout 或 stderr。
