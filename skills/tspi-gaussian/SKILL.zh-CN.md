---
name: tspi-gaussian
description: 准备和评估 Gaussian 单点、优化、频率与 IRC 计算，并将结果记录为 Node 产出。
---

# TSPi Gaussian

[English version](SKILL.md)

当任务涉及 Gaussian 输入和输出校验时使用本 Skill。ResearchMap 与计算合同使用
`tspi-orchestration`；IRC 端点身份使用 `tspi-connectivity`。

将输入绑定为 `gjf` Artifact，并在计算意图中保留方法、基组、电荷、多重度、环境、
资源和关键词。核对正常结束及其与意图的一致性，分别检查优化收敛、频率数量、模式、
IRC 路径、电子态和热化学。

对于一阶鞍点，核验一个虚频，把位移对应到所提步骤，并确认端点连通性。核验过的数值
记录为 `FactFinding`；SCF 不稳定、自旋污染、态歧义、警告和方法敏感性记录为
`IssueFinding`，并引用原始输出 Artifact。

校验清单见 [gaussian_validation.md](references/gaussian_validation.md)。候选生成使用
`tspi-transition-state-search`，端点归属使用 `tspi-connectivity`。
