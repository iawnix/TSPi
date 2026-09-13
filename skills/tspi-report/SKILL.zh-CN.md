---
name: tspi-report
description: 构建包含研究结论、支持证据、计算历史、验证结果和图像的 TSPi 研究报告。
---

# TSPi 报告

[English version](SKILL.md)

使用本 Skill 处理 `ts_report`。工作区状态、产物身份、验证和 Decision 合同使用
`tspi-orchestration`；报告需要可视化产物时加载 `tspi-render`。

## 操作规则

- 仅从完整且有效的工作区和已注册的逻辑 artifact ID 构建报告。
- 分开记录 scientific revision、operational revision、接受状态、Finding、
  限制和未决问题。
- 生成报告前，通过 `ts_change` 记录 Node 和 Claim 的当前状态；阶段性报告应
  包含进行中的工作和未决问题。
- 每条科学陈述都引用当前 Observation、ProofSpec、ValidationResult、Finding
  和主产物引用。
- 每次导出创建新报告包，返回前核对文件和 revision 与 manifest 一致。

必需的投影内容、接受措辞、数值纪律和包完整性规则见
[report_template.md](references/report_template.md)。
