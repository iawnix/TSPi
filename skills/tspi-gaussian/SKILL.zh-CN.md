---
name: tspi-gaussian
description: 使用绑定科学意图的输出证据准备和评估 Gaussian 单点、优化、频率与 IRC 计算。
---

# TSPi Gaussian

[English version](SKILL.md)

当任务涉及 Gaussian 输入准备和输出验证时使用本 Skill。计算与证据合同使用
`tspi-orchestration`；IRC 端点身份使用 `tspi-connectivity`。

## 证据规则

- 用逻辑 artifact 绑定 Gaussian 输入 `gjf`，并在不可变意图中保留 route、方法、
  基组、电荷、多重度、环境、资源和相关关键词。
- 检查原始输出是否正常结束且是否符合意图；调度器成功和文件存在都不够。
- 将优化收敛、频率数量、模式赋值、IRC 路径、电子态问题和热化学作为独立
  Observation。
- 普通一阶鞍点需要一个虚频，但这不能证明反应步骤。Gaussian 正常结束也不能
  证明连通性、机理或热化学结论。
- 将 SCF 不稳定、自旋污染、态身份歧义、警告和方法敏感性记录为 Finding 或
  明确 Observation。

## 参考资料

验证维度和版本化 ProofSpec 见 `references/gaussian_validation.md`。QST 等候选
策略使用 `tspi-transition-state-search`，端点赋值使用 `tspi-connectivity`。
