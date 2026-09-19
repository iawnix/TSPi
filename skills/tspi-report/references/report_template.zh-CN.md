# 报告合同

使用 `ts_report` 从当前 `ResearchMap` 与已注册逻辑 Artifact 构建报告。报告是 map revision
和所选运行记录组成的包，不是新的状态模型。

## 必需内容

包括：

1. map identity、revision、焦点 Claim/Node 与结论边界；
2. map 存在 Phase 时的可选 Phase 分组；
3. Claim 与 Claim 关系，包括替代与冲突；
4. Node objective、依赖、state、outcome 与未决问题；
5. calculation intent 与主要 Artifact 引用；
6. 带 value、unit、provenance 与来源引用的 FactFinding；
7. IssueFinding，包括未解决局限与冲突；
8. Gate 及其 criteria 与 evaluation；
9. 运行后续事项，例如待处理 run、失败 Attempt、Review 建议和通知状态；
10. 缺失校正、不确定性与下一项研究问题。

不要为未分组 Node 合成 Phase。Phase 只是可选导航，因此没有 Phase 时报告仍应保持有意义
的顺序。

## 数值规范

区分电子能、E+ZPE、焓与自由能。报告单位、参考态、温度、压力、标准态校正、频率 scaling、
构象处理、溶剂化、色散与缺失校正。不可用值标记为 missing。每个数值或结构陈述引用一个
FactFinding 及其来源 Artifact；证据不完整时由 IssueFinding 承载局限。

## 包完整性

每次导出创建新的包目录。Manifest 绑定来源 map revision、运行记录、文件路径、大小与
SHA-256 摘要。只有 manifest 与实际普通文件匹配时，包才可使用。不要编辑已生成报告后
将其表示为更新的 ResearchMap revision。
