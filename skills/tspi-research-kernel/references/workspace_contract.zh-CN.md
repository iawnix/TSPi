# 研究 Workspace 合同

## 规范状态

每个研究 workspace 拥有 `workspace.json`、一个 `research_map.json`、
`transactions.jsonl`、输入目录 `inputs/`，以及 `nodes/<node_id>/` 下由 Node 所有的目录。
`research_map.json` 包含完整 ResearchMap：phase、claim、node、finding、gate、Claim 关系、
焦点、metadata 与 revision。TS Web 和 Root 直接消费该文档。Compute Attempt 与 Artifact
位于 Node 所属目录，可被 map 对象引用。

## 初始化与身份

通过 `workspace.engine.init_workspace()`，或调用同一 workspace 初始化边界的 Host
bootstrap 创建 map。Map identity 与对象 ID 都是 workspace 本地的。Kernel 拒绝格式错误
的 JSON、重复 ID、未知引用、环、无效 enum 值和不一致的反向索引。所有 Artifact 引用都
保持为逻辑、workspace 相对引用；不要把绝对或远端路径写入 map 对象。

规范科学状态文件是 `research_map.json`。Bootstrap 遇到不支持的 workspace 时会拒绝，
不会重写它。

## 写入边界

常规流程为：

```text
ts_state -> Root interpretation -> ts_change
```

`research.change` 在锁内加载当前 map，把有序 ChangeSet 应用到独立副本，校验完整变更后
状态，递增 revision，并原子替换 `research_map.json`。被拒绝的请求不会改变之前的
revision。不要手工编辑 JSON 或 transaction log。

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
报告包、通知与 UI 状态都属于运行记录。Root 核验主要 Artifact 后，Finding 可以通过
`source_refs` 引用这些记录。一次成功执行绝不会自动改变 Claim 或 Node。
