---
name: tspi-render
description: 从已注册的 TSPi 结构生成确定性的可视化产物，用于检查、比较、动画和机理展示。
---

# TSPi 渲染

[English version](SKILL.md)

使用本 Skill 处理 `ts_render`。工作区、产物、活动和证据合同使用
`tspi-orchestration`。渲染属于展示能力，不能单独建立科学结论。

## 操作规则

- 通过 `ts_state mode=artifacts` 解析输入产物，不根据用户文本拼接工作区路径。
- 明确所属 ResearchNode、逻辑 artifact ID、输出名称和操作类型。
- 将 `render`、`animate`、`compare` 和 `mechanism` 视为独立操作，分别遵守
  输入数量和输出格式要求。
- 检查输出及其摘要；科学数值仍须通过已核验的主产物和正常的
  `ts_change` Decision 记录。

请求校验、输出归属、渲染器边界和失败处理见
`references/render_contract.md`。
