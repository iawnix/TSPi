# ADR 0003：最小 Research Kernel 与 Gate 合同

[English](0003-minimal-research-kernel-and-gates.md) | 简体中文

- 状态：提议
- 日期：2026-09-16

## 决定

Research Kernel 是 Claims、ResearchNodes、Observations、Findings 及其引用、稳定 ID、
artifact ownership、revision、Gate 定义冻结、确定性 Gate 评估和 Research Map
projection 的事务与完整性边界。

Kernel 不选择科学方法、下一 Node、backend、远程作业、邮件或图形，也不从工具成功
自动推导 Claim 状态。在 Agent 边界上，它表现为受保护的 `ts_state` 与 `ts_change`。

## 统一 Gate 合同

NodeGate 和 ClaimGate 只是同一合同的两个作用域：

```text
GateSpec   = 冻结的收尾/评估标准
GateResult = 绑定 GateSpec digest 和输入 revision 的一次评估
scope      = node | claim
```

结果只能是 `pass`、`fail`、`inconclusive` 或 `blocked`。`blocked` 表示前置条件或工具
结果缺失，不是科学反驳。GateSpec 冻结后不可修改；改变标准必须产生新 spec。NodeGate
通过只允许 Node 关闭，不表示 Claim 成立；ClaimGate 也不会自动更新 Claim 或创建
Acceptance。

Root Agent 选择研究意图和 profile，Skill/Plugin 声明能力和谓词，Kernel 展开 profile、
校验目标引用、绑定 registry 并冻结 digest。旧工作区没有 Gate registry 仍然有效，
显式 `freeze_gate` / `evaluate_gate` 首次写入时再惰性创建。

Research Map、报告和 context 只能消费 projection，不得成为第二个 Gate evaluator 或
状态存储。
