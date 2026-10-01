---
name: tspi-gaussian
description: 根据已注册输入执行器准备、运行并检查 Gaussian 单点、优化、频率、扫描、过渡态、IRC 与 QST 计算。
---

# TSPi Gaussian

[English version](SKILL.md)

使用本 Skill 处理 Gaussian 特有的输入构造、执行、解析与输出检查。方法选择由
`tspi-method-selection` 负责，TS 的科学验证由 `tspi-ts-validation` 负责，路径的化学
意义由 `tspi-irc` 负责。

把每个 `.gjf` 输入绑定为 ResearchNode Artifact。在不可变 intent 中保留 route、方法、基组、
电荷、多重度、溶剂、资源、任务与相关关键词。检查输出是否与 intent 一致，选择正确的
job section，并分别评估终止状态、SCF、优化收敛、频率证据、几何、电子态、IRC 数据与
热化学和扫描曲线，不要把它们混成一个结论。Gaussian 输入的 Route Section 决定计算模式，
所有支持的模式统一提交给已注册的 `gaussian@1` 执行器，不再注册 `sp`、`freq`、`opt`、
`irc` 或 `scan` 变体。

QST2/QST3 由 Gaussian 输入的 Route Section 表达，并继续接受输入和输出校验。Skill 不注册
capability，实时 Native catalog 中的 `gaussian@1` 才是提交依据。

核对原始文件后再记录解析结果。正常终止不等于任务验证，两者也都不等于科学结论。明确
记录 SCF 不稳定、自旋污染、态歧义、缺失校正与方法敏感性。详见
[gaussian_validation.zh-CN.md](references/gaussian_validation.zh-CN.md)。优化后继续单点计算时，必须使用
结果中的 `optimized_input_artifact_id`，并确认 Artifact 类型为 `chemical/gaussian-input`；最终
几何位于 `optimized_geometry_artifact_id`。不能把 stdout/stderr 或 `artifact_ids` 中的任意位置项作为输入。
