# 连通性验证

连通性问题询问候选路径是否到达 Claim 声明的反应物与产物势阱。它与驻点和虚频模式
检查相互独立。

## 检查清单

对每个方向检查程序正常终止、路径完成、最后几何与梯度、必要时的端点优化，以及端点与
所声明反应物或产物 Artifact 的归属。显式保存方向、来源路径、端点优化和摘要引用。

核验原子映射、元素计数、电荷、多重度/电子态、相关同位素、成键变化、内坐标、立体化学，
以及短路径或最大步数限制。使用 `artifact_compare` 进行确定性几何与立体化学检查。

## 记录与评估

把已核验归属、mapping、RMSD、坐标和来源引用记录为 `FactFinding`。缺少方向、端点、路径
完成或 identity 证据时记录 `IssueFinding`。冲突归属也记录为包含双方来源引用的
IssueFinding。Finding 为决策提供信息，但不会自动改变 Node state 或 Claim status。

只有端点 identity、路径完成或立体化学保持等 criterion 需要可见 verdict 时，才创建
NodeGate 或 ClaimGate。使用当前证据引用评估；Gate 不会改变 Claim status。
