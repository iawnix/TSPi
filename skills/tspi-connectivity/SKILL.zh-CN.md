---
name: tspi-connectivity
description: 根据明确的结构证据验证反应路径端点、原子映射、立体化学和分子盆地身份。
---

# TSPi 连通性

[English version](SKILL.md)

当问题是候选路径是否到达声明的反应物和产物盆地时使用本 Skill。ProofSpec 和
artifact 合同使用 `tspi-orchestration`，Gaussian 输出验证使用 `tspi-gaussian`。

结合驻点和虚频验证评估连通性，通过原子映射、成键、立体化学和几何比较，
将有限 IRC 端点归属到相应的分子盆地。

## 证据规则

- 保留路径方向，并明确哪个端点是反应物或产物。
- 检查最后几何和梯度；必要时优化端点。
- 核对元素数量、电荷、多重度/电子态、相关同位素、原子映射、成键变化、内部
  坐标和立体化学。
- 使用带版本的 `connectivity` ProofSpec 和明确 Observation 引用。缺少方向、
  端点、路径完成或身份证据时保持 inconclusive，或产生阻断 Finding。
- 将映射方法、选定原子、RMSD、关键坐标、原始 artifact 摘要和限制记录为语义
  Observation。

内置连通性维度见 [connectivity_validation.md](references/connectivity_validation.md)；确定性的 `ts_compare`
参数和结构身份规则见 [ts_structures_contract.md](references/ts_structures_contract.md)。
