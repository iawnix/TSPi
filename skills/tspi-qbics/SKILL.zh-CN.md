---
name: tspi-qbics
description: 在明确配置和电子态特征证据的前提下规划和评估 QBICS DMECP 电子态交叉计算。
---

# TSPi QBICS / DMECP

[English version](SKILL.md)

当任务使用已注册的 `qbics.dmecp` 能力时使用本 Skill。任务、产物和状态合同
使用 `tspi-orchestration`；当交叉候选属于更大候选生成策略时再使用
`tspi-transition-state-search`。

QBICS/DMECP 处理电子态交叉问题。输出在相关电子态身份、能量、几何和物理解释
经过核验前视为交叉候选。根据所研究的电子态交叉选择验证条件。

## 操作规则

- 用一个 QBICS 配置 artifact 绑定计算意图。
- 在配置和 Node 理由中保留态标签、电荷、多重度、方法和收敛设置。
- 检查两个预期原始产物：`dmecp_candidate.xyz` 和 `dmecp_summary.json`，以及
  程序状态和 parser 证据。
- 输出支持时，将态特征、交叉几何、能隙、梯度和方法限制记录为独立 Observation
  或 Finding。缺少态证据时保持 inconclusive。
- 使用适合该 Claim 的已注册电子结构或态特征 ProofSpec；所需检查尚不可用时，
  记录验证缺口。

通过能力描述查询接受的输入，通过远端诊断检查软件环境，再将核验后的交叉点
联系到研究假设。
