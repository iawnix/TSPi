# ADR 0006：统一 Research Harness 生命周期与边界

> Historical archive / 历史归档：本文记录旧设计或一次性验证，不是当前接口合同，也不代表本次重构已通过验收。当前设计见 [Research Memory plan](../../RESEARCH_MEMORY_DESIGN_AND_IMPLEMENTATION_PLAN.zh-CN.md)。

> Historical design record. Research graph and lifecycle guidance is superseded by the [current notebook architecture](../../ARCHITECTURE.md).

## 状态

已接受。

## 背景

TSPi 之前把 Agent 的 turn 结束、LifecycleAction、Monitor wake 和计算 Attempt
分散在不同适配器中。一个 lifecycle action 完成后，如果 Agent 没有再登记下一步，
Host 会把“当前 action 已完成”误当成“研究可以结束”；反过来，Host 也可能
把一个已经登记的 `required` 下一步在同一个 turn 里再次注入，导致同一研究 scope
被连续推进。

研究状态必须由 Research State 推导，生命周期必须由 Harness 统一执行。Host/Monitor
不能替 Agent 选择科学方法，Attempt 的终止也不能自动生成 Finding 或 Claim 结论。

## 决策

### 单一职责

```text
Agent
  读取 bounded Research Memory，选择问题、方法、Skill、Capability 和停止条件
  解释 Attempt/Artifact，提交 Finding/Gate/Claim/Node ChangeSet
  在每轮结束调用 research_checkpoint 登记 continue_required、waiting_external、
  deferred、blocked、terminal 或 user_input_required disposition

Research State
  唯一科学状态权威：ResearchMap、ChangeSet、引用完整性和 liveness
  推导研究是否需要决策，不执行计算、不解释 Artifact、不选择方法

Harness / Host
  管理 turn admission、权限、workspace/session 绑定、工具契约、恢复和 follow-up
  管理输入消费和工具准入；从 State 的 liveness 投影决定是否需要有界 follow-up

Monitor
  观察外部 Attempt，记录 event/delivery，并通过 next_run 唤醒绑定 session
  不修改 ResearchMap，不 finalize，不产生科学解释

Compute / Workspace Runtime
  执行 Attempt，收集并解析 Artifact，维护 environment/capability operational state
  不直接写 Finding、Claim 或 Gate
```

### Host 与 Research State 的职责

普通输入、Monitor wake 和恢复都通过当前 Pi submission 与 Worker 路径进入。Research
State 不提供通用的 turn request/result 协议，也不保存 turn audit。Host/Harness
负责输入准入、工具权限、workspace/session 绑定和恢复；Research State 负责规范研究状态、
checkpoint 与 liveness。计算开始、结束或 Monitor 通知本身都不能生成科学结论。

Worker 使用有界上下文和 State 工具执行当前 run。Agent 可以通过 `research_checkpoint`
记录 `continue_required`、`waiting_external`、`deferred`、`blocked`、`terminal` 或
`user_input_required` disposition。`continue_required` 记录明确的后续动作；它不会让
Host 在当前 run 中自行选择并执行科学方法。Native Worker 在 run yield 后读取 liveness；
若 active scope 仍缺少 disposition，可以请求有界 follow-up。Host 可以要求 Agent 读取
状态并登记 disposition，但不能替它选择方法、Capability、Backend、Skill、参数或科学结论。

```text
Pi submission -> Host admission -> Root Agent run -> State/Runtime tools
              -> optional bounded follow-up based on State liveness
```

Monitor 在创建输入前调用只读命令 `research.monitor_assess(event_id, session_id)`。Research
State 在 workspace 锁内检查事件的 workspace/session 身份，并将 event 与当前 Attempt、Node、
interpretation、collection 和 disposition 对照，判断是否已处理或仍需关注。该结果只是准入
评估，不是输入回执。Host 将通过检查的输入持久化为 Pi submission，并在模型首次消费前再次
评估；Pi submission 是输入状态和消费的唯一权威，过期或被替代的 Monitor 事件不能进入模型。

### Liveness 语义

Research State 只返回以下状态：

- `idle`：没有 active scope；
- `continue_required`：Agent 已登记明确的下一 turn 动作。这是合法的 turn 终态，Host 不得强制本轮执行；
- `waiting_external`：存在已提交、排队、运行中、完成但未解析或状态未知的 Attempt；
- `decision_needed`：active Node/Claim/Gate 没有 `continue_required`、等待、deferred、blocked 或 terminal disposition。如果 liveness 同时带有 `execution_ready=true`，表示 focus 已有 active StrategyPlan，Host 可以在 checkpoint 前放行已声明的 prepare/execute；Agent 仍必须在 turn 结束前写入 checkpoint；
- `deferred`：Agent 明确记录了原因和后续恢复条件；
- `blocked`：Agent 明确记录了阻塞原因和恢复条件；
- `terminal`：相关 scope 已关闭或研究没有开放 scope。

生命周期动作是通过 `research.change` 的 `set_lifecycle_action` 和
`resolve_lifecycle_action` 操作登记的规范 State 记录。`research.liveness` 只是诊断投影，不负责
持久化下一步或关闭 turn。

Attempt/Artifact/LifecycleAction 的完成都不是研究完成的同义词。只有 ResearchMap 的
Node/Claim/Gate 状态和 Finding/Gate 证据决定科学结论。

### Follow-up 规则

Native Worker 在模型 run yield 后读取 Research State 的 liveness：

- `accepted=true`：结束当前 turn；`continue_required` 计划留给后续 turn 或 Monitor wake；
- `requires_disposition=true`：最多追加有界 follow-up，要求 Agent 重新读取
  `research_read(mode=context|liveness)`，然后通过 `research_checkpoint` 或
  `research_change` 登记 disposition；只有迁移旧记录时才使用 `research_checkpoint`；
- Host 不得在 follow-up 中指定 Capability、Backend、Skill、计算参数或科学结论；
- 达到 follow-up 上限后保留 `decision_needed`，不能伪造 `terminal`。

Monitor 的 wake 只是 operational 输入，不是新的科学指令。事件是否仍需处理由只读
`research.monitor_assess` 评估；输入的持久化、去重及消费状态由 Pi submission 管理。
Research State 不再维护并行的 delivery receipt 或 turn audit。

### Research Memory、Skill 与计算环境

Durable Research Memory 保存在 workspace：ResearchMap、ChangeSet、Attempt、Artifact、
Monitor event 和 provenance。模型上下文不是第二份状态；run 生命周期由 Host/Pi 管理，
Research State 不复制一份 turn history。

每个 turn 只生成 bounded `research.context`：当前 focus、Gate/LifecycleAction 摘要、
Attempt 状态、liveness 和截断标记。需要完整对象时 Agent 使用 `research_read detail/locate`
或专门的 Artifact 查询。

Skill 使用 manifest-first、body-on-demand：Session 启动只将 name/description/location
放入模型可见 prompt；正文可以由 worker 在 resources 中缓存，但只有显式 Skill operation
才注入当前 turn，并将 digest/provenance 写入 operational audit。Compute Environment 同样只在默认上下文中提供 identity/readiness
摘要，launch 或方法选择前再读取具体 Backend capability；list/show 返回 source digest、
identity digest 和 readiness，而不是默认暴露完整命令、scratch 或环境变量。

### 工具契约

每个公开工具必须声明：

```text
authority  effect  replay/idempotency  phase
workspace/session binding  input schema  output schema  error taxonomy
```

Research Write 只能经过 Research State ChangeSet；Execution 只能创建 Attempt/Artifact；Read
只能返回 bounded read model；Advisory 不拥有科学状态；External Side Effect 必须显式
标记并禁止科学状态自动重试。所有 transport 使用 `tspi-tool-result/1` 和
`tspi-tool-error/1` envelope。

运行时强制在工具 admission 边界集中执行。每个生产工具必须提供 `label`、`description`、参数 schema、
可执行的 `execute` 函数以及完整且精确的四字段 Harness metadata。公共工具名必须匹配 canonical metadata
注册表；未知 metadata 值、额外字段或公共工具 metadata 漂移会在 Worker 创建前被拒绝。结果适配器也会拒绝
格式错误的 content，并持久化 `tool_contract_violation`，不会把非法结果交给 Pi Core。

工具错误统一使用有限分类：`validation`、`authorization`、`workspace`、`conflict`、`ambiguous`、
`transient`、`execution`、`contract`。显式的 `retry_safe` 只能让允许重试的 execution 错误可重试；transient 错误默认可重试，
validation、authorization、workspace、conflict、ambiguous 与 contract 错误绝不会被静默重放。

调用级别同样由 Harness 强制执行：Host 创建带有不可伪造标记的 `ToolExecutionContext`，其中绑定
workspace root、session、operation、lifecycle phase、replay mode 以及允许的 authority/effect/phase
策略。工具 wrapper 在进入实现函数前绑定当前 invocation 并拒绝缺失或伪造 context、phase/authority/effect
不匹配、workspace 或 session 冲突、缺少 operation identity，以及恢复期间调用不可重放工具。Agent 只能提交
普通工具参数，不能在参数中声明或扩大这些执行权限。

Native Worker 通过 Host 私有的同步 lifecycle provider 提供这份 context。`before_drive` 先把一个尚未看到新
`before_run` 的 operation 暂记为 recovery；新 prompt 被接纳后，`before_run` 再把它确定为 normal 或
Monitor-wake turn。`before_tool` 只允许 Host 阶段图中的下一阶段，成功的 `after_tool` 再推进阶段。每次
真正调用工具前都会刷新 provider，因此同一个 run 的多个 tool batch 能看到当前阶段，而 Agent 参数不能修改
policy。这样冷恢复只允许 safe/idempotent 的 reconcile，`replay: never` 的副作用会在进入实现函数前被拒绝。

## Native 生命周期接口

`research_read`（包括有界的 `liveness` 视图）和 `research_checkpoint` 是
Agent/Host 的规范研究状态接口：前者提供有界状态，后者持久化 disposition。
`research.liveness` 是派生诊断视图。Native Worker 在 run yield 后读取同一 liveness
投影，并只在 active scope 缺少 disposition 时请求有界 follow-up；它不创建第二套研究
状态机。Monitor 事件则通过只读 `research.monitor_assess` 进行 workspace/session 绑定检查。

## 验证

必须覆盖：缺少 disposition、显式 continue_required、waiting external、deferred/blocked、terminal、
Monitor event 与 workspace/session 绑定、重复/迟到事件在 Pi submission 消费前复核、parsed
Attempt 后重新需要决策、bounded context、工具 envelope 和 Skill/Environment lazy-read contract。
