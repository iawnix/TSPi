# ADR 0006：统一 Research Harness 生命周期与边界

## 状态

已接受。

## 背景

TSPi 之前把 Agent 的 turn 结束、Continuation、Monitor wake 和计算 Attempt
分散在不同适配器中。一个 continuation 完成后，如果 Agent 没有再登记下一步，
Host 会把“当前 continuation 已完成”误当成“研究可以结束”；反过来，Host 也可能
把一个已经登记的 `required` 下一步在同一个 turn 里再次注入，导致同一研究 scope
被连续推进。

研究状态必须由 Research Kernel 推导，生命周期必须由 Harness 统一执行。Host/Monitor
不能替 Agent 选择科学方法，Attempt 的终止也不能自动生成 Finding 或 Claim 结论。

## 决策

### 单一职责

```text
Agent
  读取 bounded Research Memory，选择问题、方法、Skill、Capability 和停止条件
  解释 Attempt/Artifact，提交 Finding/Gate/Claim/Node ChangeSet
  在每轮结束调用 research_checkpoint 登记 continue_required、waiting_external、
  deferred、blocked、terminal 或 user_input_required disposition

Research Kernel
  唯一科学状态权威：ResearchMap、ChangeSet、引用完整性和 liveness
  推导研究是否需要决策，不执行计算、不解释 Artifact、不选择方法

Harness / Host
  管理 turn admission、权限、workspace/session 绑定、工具契约、恢复和 follow-up
  在统一 research.turn boundary 执行 checkpoint，不拥有科学决策

Monitor
  观察外部 Attempt，记录 event/delivery，并通过 next_run 唤醒绑定 session
  不修改 ResearchMap，不 finalize，不产生科学解释

Compute / Workspace Runtime
  执行 Attempt，收集并解析 Artifact，维护 environment/capability operational state
  不直接写 Finding、Claim 或 Gate
```

### Canonical Research Turn

所有入口（普通用户 turn、Monitor wake、恢复和重试）都经过同一协议：

```text
TRIGGER -> ADMIT -> ORIENT -> PLAN -> PREPARE -> EXECUTE
        -> WAIT/RECONCILE -> INTERPRET -> ADVANCE -> CHECKPOINT
        -> END 或 WAKE
```

Kernel 暴露 `research.turn`（`research-turn-request/1` / `research-turn-result/1`）：

- `start`：登记一次 turn 开始并返回 bounded liveness；
- `orient`：返回 bounded Research Context 和 liveness；
- `checkpoint`：检查 Agent 是否留下合法 disposition；
- `end`：只有非 `decision_needed` 状态才接受 turn 结束；
- `wake`：把 Monitor/恢复唤醒映射到同一个边界。

`research.turn` 只记录 operational turn audit（`operations/research_turns.jsonl`），
不把生命周期事件写入 ResearchMap 科学事实集合。提供的 `request_id` 是幂等键：完全相同的重试返回
`replayed=true` 且不重复追加 audit；如果同一 key 被用于不同 operation、turn、session、trigger
或 delivery identity，则拒绝该 command。

### Liveness 语义

Kernel 只返回以下状态：

- `idle`：没有 active scope；
- `continue_required`：Agent 已登记明确的下一 turn 动作。这是合法的 turn 终态，Host 不得强制本轮执行；
- `waiting_external`：存在已提交、排队、运行中、完成但未解析或状态未知的 Attempt；
- `decision_needed`：active Node/Claim/Gate 没有 `continue_required`、等待、deferred、blocked 或 terminal disposition；
- `deferred`：Agent 明确记录了原因和后续恢复条件；
- `blocked`：Agent 明确记录了阻塞原因和恢复条件；
- `terminal`：相关 scope 已关闭或研究没有开放 scope。

旧的 `required` 值只在读取或迁移兼容的 `research_continuation` ledger 时接受，并规范化为
`continue_required`；它不是另一套生命周期状态。`research.liveness` 只是诊断投影，不负责
持久化下一步或关闭 turn。

Attempt/Artifact/Continuation 的完成都不是研究完成的同义词。只有 ResearchMap 的
Node/Claim/Gate 状态和 Finding/Gate 证据决定科学结论。

### Follow-up 规则

Host 在 `checkpoint/end` 读取 Kernel 的结果：

- `accepted=true`：结束当前 turn；`continue_required` 计划留给后续 turn 或 Monitor wake；
- `requires_disposition=true`：最多追加有界 follow-up，要求 Agent 重新读取
  `research_read(mode=context|liveness)`，然后通过 `research_checkpoint` 或
  `research_change` 登记 disposition；只有迁移旧记录时才使用 `research_continuation`；
- Host 不得在 follow-up 中指定 Capability、Backend、Skill、计算参数或科学结论；
- 达到 follow-up 上限后保留 `decision_needed`，不能伪造 `terminal`。

Monitor 在确认 wake delivery 前先提交 `research.turn(operation=wake)`；如果 boundary
失败，delivery 保持 pending 并重试。因此 Monitor 的 `next_run` 是 operational wake-up，不是新的科学指令；`handoff` 只表示
session/Agent 生命周期转移，也不表示科学下一步。

### Research Memory、Skill 与计算环境

Durable Research Memory 保存在 workspace：ResearchMap、ChangeSet、Attempt、Artifact、
Monitor event、turn audit 和 provenance。模型上下文不是第二份状态。

每个 turn 只生成 bounded `research.context`：当前 focus、Gate/Continuation 摘要、
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

Research Write 只能经过 Kernel ChangeSet；Execution 只能创建 Attempt/Artifact；Read
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
Agent/Host 的规范接口：前者提供有界状态，后者以 disposition 结束 turn。
`research.liveness` 只是诊断；`research_continuation` 仅用于读取或迁移旧的
required-action ledger。所有生命周期语义统一由 `research.turn` 解释。Native
Worker 的 `before_run_end` 只调用同一个 lifecycle boundary，不得实现第二套
liveness 或 continuation 状态机。

## 验证

必须覆盖：缺少 disposition、显式 continue_required、waiting external、deferred/blocked、terminal、
Monitor wake、parsed Attempt 后重新需要决策、turn audit 幂等边界、bounded context、
workspace binding、工具 envelope 和 Skill/Environment lazy-read contract。
