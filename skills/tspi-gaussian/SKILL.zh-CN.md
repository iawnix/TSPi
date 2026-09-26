---
name: tspi-gaussian
description: 准备、运行并检查已注册的 Gaussian 单点、优化、频率、扫描、过渡态与 IRC 计算，并提供 QST 输入指导。
---

# TSPi Gaussian

[English version](SKILL.md)

使用本 Skill 处理 Gaussian 特有的输入构造、执行、解析与输出检查。方法选择由
`tspi-method-selection` 负责，TS 的科学验证由 `tspi-ts-validation` 负责，路径的化学
意义由 `tspi-irc` 负责。

把每个 `.gjf` 输入绑定为 Node 所属 Artifact。在不可变 intent 中保留 route、方法、基组、
电荷、多重度、溶剂、资源、任务与相关关键词。检查输出是否与 intent 一致，选择正确的
job section，并分别评估终止状态、SCF、优化收敛、频率证据、几何、电子态、IRC 数据与
热化学和扫描曲线，不要把它们混成一个结论。Gaussian relaxed scan 必须使用已注册的
`gaussian.scan@1` capability；不要把含有 `Scan` 的输入伪装成 `gaussian.sp`。

本版本的 QST2/QST3 只负责输入构造与方法指导，并不是已注册的执行 capability。只有
`research.read mode=capabilities` 返回的 descriptor 才能用于提交；不要把 QST 输入标记为
`gaussian.ts`。

核对原始文件后再记录解析结果。正常终止不等于任务验证，两者也都不等于科学结论。明确
记录 SCF 不稳定、自旋污染、态歧义、缺失校正与方法敏感性。详见
[gaussian_validation.zh-CN.md](references/gaussian_validation.zh-CN.md)。
