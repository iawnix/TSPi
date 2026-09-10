---
name: tspi-report
description: 构建由证据绑定的确定性 TSPi 报告包，展示科学和运行状态但不改变工作区。
---

# TSPi 报告

[English version](SKILL.md)

使用本 Skill 处理 `ts_report`。工作区状态、产物身份、验证和 Decision 合同使用
`tspi-orchestration`；报告需要可视化产物时加载 `tspi-render`。

## 操作规则

- 仅从完整且有效的工作区和已注册的逻辑 artifact ID 构建报告。
- 分开记录 scientific revision、operational revision、接受状态、Finding、
  限制和未决问题。
- 报告是状态投影和交付产物，不能修复、完成或接受 ResearchNode。
- 每条科学陈述都引用当前 Observation、ProofSpec、ValidationResult、Finding
  和主产物引用。
- 只返回文件和 revision 与 manifest 一致的新报告包，禁止覆盖既有报告包。

必需的投影内容、接受措辞、数值纪律和包完整性规则见
`references/report_template.md`。
