# ResearchMap 设计说明

[English](PLAN_HYPOTHESIS_PROOF_LOOP.md) | 简体中文

本文记录当前简化后的研究模型，不是第二套协议，也不是兼容层计划。

## 规范状态

一个项目只拥有一个 `research_map.json`。`ResearchMap` 是类型化聚合，包含
`ResearchPhase`、`ResearchClaim`、`ResearchNode`、`Finding` 和 `Gate`。其中
`FactFinding`、`IssueFinding` 是同一个 `Finding` 结构的特化，`NodeGate`、
`ClaimGate` 是同一个 `Gate` 结构的特化。反向索引和图依赖都属于 map，并由模型
统一校验。

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

## Kernel 边界

`ResearchKernel` 是唯一的变更权威。调用方提交带期望 revision 的 ChangeSet 和有序
操作。Kernel 在隔离副本上校验操作目录、引用、反向索引、循环和状态转换，然后原子
写入 map 并追加事务回执。失败请求不会改变旧 revision。

统一命令面为：

```text
research.map        完整 map
research.summary    进展和 focus
research.detail     一个 map 对象
research.locate     在 map 对象中搜索
research.validate   校验 map
research.operations 操作目录
research.change     应用一个 ChangeSet
```

CLI、Pi tools、slash command、Root Agent 和 TS Web 使用同一组命令。`/research` 只是
命令服务的交互写法，不是另一套 API。`/compute` 通过 `compute.environments` 和
`compute.environment` 查询统一的本地/远端环境目录。

## 执行与 Finding

Skill 描述流程和能力，Backend 实现软件，Platform 描述本地、容器或 HPC 环境。
一份 `compute.toml` 同时保存 local/remote environment，由 environment 的 `kind` 决定传输
细节。Calculation Attempt 和 Artifact 是 Node 所有的操作记录。解析器或分析能力可以
产生临时候选结果，但只有显式 ChangeSet 才会在 map 中创建 `FactFinding` 或
`IssueFinding`。工具成功不会自动修改 Claim 或关闭 Node。

## 客户端与报告

`ResearchMap.to_dict()` 是 TS Web、Root Agent 和报告直接消费的规范序列化。客户端可以
为了展示进行筛选和分组，但不创建第二个科学状态模型或 registry。操作记录与 map 分开展示。
Gate 保存 criteria 和评估历史，不会静默修改目标对象。

## 交付检查

- 研究状态只保留 `research_map.json`、`transactions.jsonl` 和 Node 的执行目录；
- 新的 map 行为应加入模型和 ChangeSet 操作，并配套聚焦测试；
- 每个新的 map 行为都要更新 Kernel 操作目录和聚焦测试；
- 更新 `packages/ts-agent-kernel/ts_agent/command_catalog.json` 或 `packages/ts-agent-runtime/host-api/tools.mjs`，slash command
  和 host adapter 直接消费这些定义；
- local/remote 计算统一放在一份 `compute.toml` environments 目录后面；
- 删除过时 registry、proof、acceptance 和 projection 模板，不添加别名。
