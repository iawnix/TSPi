# 研究 Workspace 合同

## 内容

- [规范状态](#规范状态)
- [初始化与身份](#初始化与身份)
- [写入边界](#写入边界)
- [关系](#关系)
- [运行记录](#运行记录)

## 规范状态

每个研究 workspace 由保持 identity 不变的 `workspace_manifest.json` 绑定。其合同要求
`schema_version=research_state_workspace_2`、`workspace_mode=research`、绝对路径
`workspace_root`、稳定的 `workspace_id`，以及 `state` 为 `admission_pending` 或 `ready`。
Manifest 负责 admission 与路由绑定；ResearchMap revision 保存在 context 与 lifecycle
投影中。
规范 workspace ID 必须匹配
`^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$`；Host 路由、Research State 请求、本地运行记录与远端计算
intent 使用同一个值。

Manifest 还固定 authority split 与目录面。Research workspace 必须包含
`profile_id=research_workspace_1`、`memory_profile=session`、`memory_scope=session`、
`research_state_scope=workspace`、`execution_profile=audited`，以及
`research_state={initialized:true, admission_required:<state 不是 ready>,
revision:<非负整数>}`。必需目录严格为 `inputs`、`artifacts`、`runs`、`logs`、
`research_map`、`memory`、`lifecycle`、`checkpoints`、`nodes`、`evidence`、`monitor`、
`environments`。Light workspace 使用同一 schema，但字段为
`profile_id=light_workspace_1`、`research_state_scope=none`、`execution_profile=bounded`、
`research_state={initialized:false, admission_required:false, revision:null}`，目录为
`inputs`、`artifacts`、`runs`、`logs`、`scratch`、`sessions`。Host、App Server、Research State 与
Monitor 读取方都必须校验这些字段；缺失或改写时直接拒绝，不能根据路径推断默认值。

规范科学状态位于 `research_map/context.json`，且必须使用
`schema_version=research_map_context_2`。即使为空，也必须存在完整的 collection surface。
必需的数组 collection 为：

```text
phases、claims、nodes、findings、gates、claim_relations、
attempts、artifacts、evidence_links、lifecycle_actions、
strategy_plans、strategy_reviews、attempt_interpretations
```

必须存在 `focus`，且其中 `claim_ids`、`node_ids` 都必须是数组。Context 的 `workspace_id`
和 `workspace_mode=research` 必须与 Manifest 一致。

生命周期 admission 位于 `lifecycle/liveness.json`，使用
`schema_version=research_liveness_2`；其 `workspace_id`、`state` 与 `revision` 必须和
Context 一致。有界运行时投影位于 `memory/index.json`，使用
`schema_version=research_memory_index_1`。它只携带 `context_revision`、生命周期、focus
metadata 与显式登记的 entries，是 metadata/lifecycle projection，不是第二个 ResearchMap，
也不是科学权威。Context、liveness 与 memory projection 由 Research State filesystem boundary 原子
写入；运行时不存在 JSON/SQLite 的备用权威。Compute Attempt 与 Artifact 的原始 payload
保留在 Node/Artifact store，context 只保存类型化元数据。

Agent Core 的 `memory_profile` 与 `memory_scope` 在 research 模式下仍然都是
`session`。持久科学状态属于 Research State，由
`research_state_scope=workspace` 表示；不要把 memory projection 当作会话记忆，
也不要通过 Core memory port 写入科学事实。

## 初始化与身份

只有 Host 可以初始化并 admit 研究 workspace。初始化创建 manifest 与 canonical
context/liveness/memory 文档并处于 `admission_pending`；Host admission 将相关文档统一变为
admitted/ready。每次读取都校验 manifest、物理文件、root、mode、ID、生命周期状态和 revision。
不完整、符号链接、旧格式或混合布局必须 fail closed，不能静默迁移。

## 写入边界

常规流程为：

```text
research_read -> Root interpretation -> research_change
```

所有 Research State 写入都必须携带 Host 绑定的身份：

```json
{"principal":"root_agent","authority":"kernel_write"}
```

该身份由 Host 附加到内部 Research State request；公共 `research_change` tool payload 不包含这两个
authority 字段。

`research_change` 在 workspace lock 内加载 canonical context，检查 `expected_revision`，在
独立副本上应用 ChangeSet 并校验完整 post-state，然后原子提交 context、liveness、memory
projection 和 manifest revision。被拒绝的请求不改变任何内容；不要手动编辑 canonical 文档。

## 关系

- Phase 可以列出其 Node；Node 可以属于一个 Phase，也可以不分组。
- Node 可以引用 Claim 与之前的 Node 依赖。
- Finding 属于一个产出它的 Node，并可引用 Claim 与来源。
- Gate 准确指向一个 Node 或 Claim，并由该目标建立索引。
- Node 依赖与 Claim 关系必须无环。
- 焦点只包含已存在的 Claim 与 Node ID。

Node state 与 Claim status 相互独立。关闭 Node 时必须提供 outcome；以 `completed` 关闭时，
所附每个 NodeGate 的最新评估还必须为 `pass`。未解决的 IssueFinding 是可见进展信息；
除非 Gate criterion 明确规定，否则它不会隐式阻止关闭。

## 运行记录

Calculation intent、Attempt、run journal、调度器回执、解析器输出、Review run、渲染文件、
报告包、通知与 UI 状态都属于运行记录。Attempt record、Artifact manifest 和 EvidenceLink
以有界元数据登记在 Evidence Registry；原始 payload 保留在 Node 目录或外部 store。Root
核验主要 Artifact 后，Finding 或 Gate 只能引用已登记且校验通过的证据。一次成功执行绝不会
自动改变 Claim 或 Node。
