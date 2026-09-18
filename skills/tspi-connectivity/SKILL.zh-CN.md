---
name: tspi-connectivity
description: 根据结构证据验证反应路径端点、原子映射、立体化学和分子盆地身份。
---

# TSPi 连通性

[English version](SKILL.md)

当问题是候选路径是否到达声明的反应物和产物盆地时使用本 Skill。ResearchMap 和
Artifact 合同使用 `tspi-orchestration`，输出检查使用 `tspi-gaussian`。

保留路径方向并标明端点，检查最后几何和梯度，必要时优化端点。核对元素数量、电荷、
多重度、同位素、原子映射、成键变化、内部坐标和立体化学；使用 `ts_compare` 做确定性
结构比较。

核验过的端点身份、映射、RMSD、关键坐标和来源 Artifact 记录为 `FactFinding`。缺少
方向、端点、路径完成或身份证据时记录 `IssueFinding`，Claim 或 Node 保持不确定。只有
确实需要可见标准时才创建 ClaimGate 或 NodeGate，不再引入单独的 proof 协议。

详见[连通性校验](references/connectivity_validation.md)和[结构合同](references/ts_structures_contract.md)。
