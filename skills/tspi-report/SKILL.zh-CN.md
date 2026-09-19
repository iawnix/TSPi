---
name: tspi-report
description: 根据规范 ResearchMap、计算历史、Finding 和可视化 Artifact 构建 TSPi 研究报告。
---

# TSPi 报告

[English version](SKILL.md)

使用 `ts_report` 时加载本 Skill。ResearchMap 语义使用 `tspi-research-kernel`，工作流
历史使用 `tspi-orchestration`，需要图像时加载 `tspi-render`。

报告必须来自有效工作区和已注册逻辑 Artifact。分开展示当前 ResearchMap revision、
Claim、Node 状态和结果、FactFinding、IssueFinding、Gate criteria/evaluations、
未决问题及计算历史。不要把运行成功写成 Claim 结论；每个数值或结构陈述都引用相关
Finding 和来源 Artifact。只有存在 Phase 时才按 Phase 分组；没有 Phase 的 map 同样完整
有效。

导出前用 `ts_state` 读取最新 map，必要时通过 `ts_change` 记录 Node 或 Claim 状态。每次
导出创建新的报告包，并检查文件、manifest、源 revision 和 Artifact 引用。详见[报告模板](references/report_template.md)。
