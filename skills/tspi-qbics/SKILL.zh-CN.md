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
经过核验前只能视为交叉候选。不能把交叉计算强行套入经典过渡态或连通性接受
配置。

## 操作规则

- 用一个 QBICS 配置 artifact 绑定计算意图。
- 在配置和 Node 理由中保留态标签、电荷、多重度、方法和收敛设置。
- 检查两个预期原始产物：`dmecp_candidate.xyz` 和 `dmecp_summary.json`，以及
  程序状态和 parser 证据。
- 输出支持时，将态特征、交叉几何、能隙、梯度和方法限制记录为独立 Observation
  或 Finding。缺少态证据时保持 inconclusive。
- Claim 需要时增加维护好的电子结构或态特征 ProofSpec，不要虚构经典 TS 通过。

能力描述只表达执行器能接受什么，不能证明 QBICS 已安装或交叉点具有科学相关性；
运行环境和科学解释必须分别核验。
