# 研究 Workspace 合同

## 规范状态

每个研究 workspace 由不可变的 `workspace_manifest.json` 绑定。规范科学状态位于
`research_map/context.json`，生命周期位于 `lifecycle/liveness.json`，有界 memory projection
位于 `memory/index.json`。三者共享 workspace ID 与 revision，由 Filesystem Research Kernel
原子写入；运行时不存在 JSON/SQLite 的备用权威。Compute Attempt 与 Artifact 的原始 payload
保留在 Node/Artifact store，context 只保存类型化元数据。

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

所有 Kernel 写入都必须携带 Host 绑定的身份：

```json
{"principal":"root_agent","authority":"kernel_write"}
```

`research_change` 在 workspace lock 内加载 canonical context，检查 `expectedRevision`，在
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
