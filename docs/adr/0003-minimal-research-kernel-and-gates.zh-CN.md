# ADR 0003：最小 ResearchMap 与 Gate 协议

[English](0003-minimal-research-kernel-and-gates.md) | 简体中文

- 状态：已接受
- 日期：2026-09-16

## 决定

`ResearchKernel` 是一个项目唯一规范 `ResearchMap` 的事务和完整性边界。
`ResearchMap` 是有类型的聚合对象，持久化为 `research_map.json`；
`nodes/<node_id>/` 下的执行记录属于执行平面，不是另一套科研状态。

```text
ResearchPhase       导航分组
ResearchClaim       科学命题与状态
ResearchNode        有界问题、工作状态与结果
FactFinding         Node 产出的确认事实
IssueFinding        Node 产出的问题、矛盾或风险
Gate                统一的目标/标准/评估协议
  NodeGate          面向 ResearchNode 的 Gate
  ClaimGate         面向 ResearchClaim 的 Gate
```

`Finding` 是同一个基类和数据结构，通过 `kind` 及特化字段区分 fact 和
issue。`Gate` 也是一个基类，`scope` 与子类标识它的目标。

`ResearchMap.to_dict()` 是规范序列化。RootAgent 和 TS Web 直接读取这份
文档；它们可以为了展示筛选记录，但不会建立第二个科学状态库。

## Gate 语义

每个 Gate 只有一个目标、标准和追加式评估历史。评估记录 `pass`、`fail`、
`inconclusive` 或 `blocked`，并保存检查时间、消息、输入 revision 和证据引用。

`NodeGate` 决定 Node 是否可以以 `completed` 结果关闭；通过 NodeGate 不会改变
任何 Claim。`ClaimGate` 记录当前 Finding 对 Claim 的评估，Claim 状态必须由
RootAgent 通过 ChangeSet 明确修改。Gate 评估不会隐式修改目标对象。

## 责任边界

Kernel 校验引用和依赖环、执行 Node 状态转换、处理乐观 revision，并原子持久化
ResearchMap。它不选择方法、不运行 Backend、不提交远程任务，也不根据工具成功
推断 Claim 状态。

Skill 描述流程和能力，Backend 实现具体软件，Platform 提供执行环境。Attempt 和
Artifact 可以通过引用关联 Node，但不会自动成为 map 中的科学对象。

## 不变量

- 所有对象都有稳定 id 和创建时间。
- Node、Claim、Finding、Gate 的引用必须在同一个 map 内解析。
- Node 依赖和 Claim 关系必须无环。
- `ready_nodes()` 根据状态和依赖推导，不持久化。
- 关闭 Node 必须给出明确 outcome。
- 有 NodeGate 时，Node 以 completed 关闭必须有最新通过评估。
- ChangeSet 原子应用，一次只增加一个 map revision。
- `research_map.json` 是唯一规范科研状态文件。

旧 registry 集合和 view/graph 协议不再兼容。TS Web、RootAgent、报告及其他
客户端都消费 ResearchMap 序列化；执行工具可以保留 Attempt/Artifact 文件，但只有
Kernel 能把它们提升为 Finding 或 Gate 证据引用。
