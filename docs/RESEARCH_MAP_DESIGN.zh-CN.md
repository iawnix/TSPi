# ResearchMap 设计说明

[English](RESEARCH_MAP_DESIGN.md) | 简体中文

本文记录当前简化后的研究模型，不是第二套协议，也不是兼容层计划。

## 规范状态

一个项目只拥有一个 ResearchMap。`ResearchMap` 是类型化聚合，包含
`ResearchPhase`、`ResearchClaim`、`ResearchNode`、`Finding` 和 `Gate`。其中
`FactFinding`、`IssueFinding` 是同一个 `Finding` 结构的特化，`NodeGate`、
`ClaimGate` 是同一个 `Gate` 结构的特化。反向索引和图依赖都属于 map，并由模型
统一校验。运行时权威文档是由 `workspace_manifest.json` 选定的
`research_map/context.json`；已废弃的 JSON/SQLite 文件只允许作为显式诊断输入，永远不是
Research State 权威。

```text
ResearchClaim -> ResearchNode -> Finding
       ^               |          |
       |               +-------- Gate
       +---------------------- ClaimGate / NodeGate
```

`ResearchPhase` 只是可选的分组和导航，不拥有另一套状态机。Node 使用明确的
`state`（`planned`、`active`、`paused`、`blocked`、`closed`）和关闭结果；Claim
有独立的 status。Node 只有在所有关联 NodeGate 的最新评估都是 `pass` 时，才能以
`completed` 结果关闭。

## Research State 边界

文件系统 Research State 是唯一的变更权威。调用方提交带期望 revision 的 ChangeSet 和有序
操作。Research State 校验操作目录、引用、反向索引、循环和状态转换，然后原子提交 context、liveness、
memory projection、checkpoint 以及 manifest revision。失败请求不会改变旧 revision。

统一命令面为：

```text
research.map        完整 map
research.summary    进展和 focus
research.context    Root Agent 使用的有界 turn context
research.liveness   根据 map 和 runtime 记录诊断生命周期
research.detail     一个 map 对象
research.locate     在 map 对象中搜索
research.validate   校验 map
research.operations 操作目录
research.decisions  有界 strategy/review/interpretation/checkpoint 历史
research.evidence   Attempt/Artifact/EvidenceLink 元数据
research.storage    规范文件系统存储状态
research.strategy   记录或评审 strategy
research.interpretation 解释 Attempt
research.checkpoint 记录研究 disposition
research.change     应用一个 ChangeSet
```

Host 使用只读命令 `research.monitor_assess`，在准入前将 Monitor event 与绑定的
workspace、session、Attempt 和当前研究状态核对。它不持久化 Pi 输入回执或 turn audit。

Agent-facing Research State port、Pi tools、slash command 和 Root Agent 使用规范命令面；
Monitor assessment 是 Host 内部调用，不是 Agent tool。`research.context` 和 `research.liveness` 是有界的诊断投影，
不持久化下一步；`research.checkpoint` 记录 disposition，
生命周期动作通过 `research.change` 作为规范 State 记录管理。liveness 响应只读地提供
`continue_required`。
`research.decisions` 与 `research.evidence` 读取 Research State filesystem boundary 投影中的有界元数据，不加载原始文件。
`/research` 只是命令服务的交互写法，不是另一套 API。
TS Web 通过 ResearchMap provider 读取 map snapshot。`/compute` 通过 `compute.environments`
和 `execution platform` 查询统一的本地/远端环境目录。

## 执行与 Finding

Skill 描述流程和能力，Backend 实现科学软件或执行器。Compute Environment 是绑定
Backend 的命名 `local` 或 `remote` 执行环境；Platform 提供远端传输和调度细节。一份
`compute.toml` 在同一目录中保存 local/remote environment。Calculation Attempt 和
Artifact 是 Node 所有的操作记录；它们的 manifest 和类型化 EvidenceLink 作为有界元数据
登记，原始文件不进入 ResearchMap。解析器或分析能力可以产生临时候选结果，但只有显式 ChangeSet
才会在 map 中创建 `FactFinding` 或 `IssueFinding`。工具成功不会自动修改 Claim 或关闭 Node。

## 客户端与报告

filesystem context 的 map-shaped projection 是 TS Web、Root Agent 和报告直接消费的规范视图。客户端可以
为了展示进行筛选和分组，但不创建第二个科学状态模型或 registry。操作记录与 map 分开展示。
Gate 保存 criteria 和评估历史，不会静默修改目标对象。

## Harness 工作流与 Monitor 准入

Root Agent 是唯一的科学决策者。它读取有界 context，通过注册的 Skill 和 Capability
选择并执行动作、解释证据，并可通过 `research_checkpoint` 登记
`continue_required`、`waiting_external`、`deferred`、`blocked`、`terminal` 或
`user_input_required` disposition。该命令负责记录研究状态，不是通用 turn 开始/结束协议。
Liveness 根据 map 和 runtime 记录派生。run yield 后，如果 active scope 仍缺少 disposition，
Host 可以请求有界 follow-up；Host 不选择科学方法，也不替 Agent 写 Finding。

普通输入、Monitor wake 和恢复都通过当前 Pi submission 与 Worker 路径进入。Monitor wake
准入前，Host 调用只读 `research.monitor_assess`，将事件和绑定 session 一起传入。Research
State 校验 workspace/session 归属，并把 event 与当前 Attempt、interpretation、collection
及 disposition 对照。Pi submission 是输入持久化的权威；Host 在模型首次消费前再次评估事件。
尚未提交的 `prepared` Attempt 仍是本地决策点，不能据此等待 Monitor event。

## 交付检查

- 研究状态包含规范 context/liveness/memory projection、Evidence/Decision 元数据和 Node 执行
  目录；原始 payload 保存在各自的 artifact store 中；
- 新的 map 行为应加入模型和 ChangeSet 操作，并配套聚焦测试；
- 每个新的 map 行为都要更新 Research State 操作目录和聚焦测试；
- 更新 `packages/tspi-runtime/tspi_runtime/command_catalog.json` 或
  `packages/agent-runtime/host-api/tools.mjs`，slash command 和 host adapter 直接
  消费这些定义；
- local/remote 计算统一放在一份 `compute.toml` environments 目录后面；
- 保持 `ResearchMap` 为唯一科学状态模型，不引入平行科学存储或别名。
- 在当前 Host/Worker 测试中覆盖 Monitor event 绑定，以及 Pi 消费前的再次核验；不要
  增加并行的 Research State turn 协议。
