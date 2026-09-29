# ADR 0007：Research Agent Framework 边界

- 状态：新框架已接受
- 日期：2026-09-26
- 范围：新的 Research Agent Framework 实现

## 决定

新框架统一命名为 **Research Agent Framework**。本实现不承担 TSPi 兼容层；
TSPi 将来作为可以建立在该框架上的 Chemistry Profile。

框架边界固定为：

```text
Contracts
  -> Agent Core
  -> Research Kernel
  -> Capability Runtime
  -> App Server
  -> Runtime Adapter / Client Adapter
```

Agent Core 负责 turn、模型请求、工具调用、上下文、重试和恢复，不拥有科研状态，
也不依赖某个具体 Agent 引擎。

Research Kernel 是唯一的科研状态权威，负责 ResearchMap、Research Memory、Claim、
Node、Finding、Gate、Evidence Link 和生命周期决策。它不选择或执行科研后端。

Capability Runtime 负责版本化 Capability descriptor、Provider adapter、Compute
Attempt、Artifact Manifest、Analysis 结果和 Environment 绑定。它不能直接写入科研
Finding 或 Claim 状态。

App Server 是应用组合根，负责 Host RPC、workspace/session 绑定、权限、回执、恢复、
Monitor 和客户端适配。它接收 `AgentRuntimePort`，不能直接 import 某个 runtime 实现。

Pi 只是一个 Runtime Adapter。Pi import、experimental source、patch 校验、Pi
SessionWorker、Pi AgentHarness 和 Pi 模型集成全部限制在
`research-agent-pi-adapter` 中。框架不调用系统安装的 `pi` 命令，也不读取环境中的
Pi 配置。

所有协议标识使用下划线命名，例如 `research_turn_request`、
`research_turn_result`、`tool_result`、`capability_descriptor` 和
`artifact_manifest`。点号协议标识无效。

新实现不保留 TSPi runtime 兼容路径、旧工具名、点号协议别名或旧生命周期入口。迁移时
可以复用科研算法和数据格式，但必须重新放到新合同后面实现。

## Runtime Port

最小的语言无关 Port 包括：

- `AgentRuntimePort`：创建、附着、提交、订阅、中断、关闭；
- `ModelPort`：描述模型并流式执行请求；
- `ContextPort`：从已准入输入构建有界、临时的 turn context；
- `MemoryPort`：读取和追加 session 级 Agent 记忆。它不是 ResearchMap 存储；
  workspace 级科研记忆写入必须经过 `KernelPort`；
- `ToolGateway`：描述并调用经过准入的工具；
- `SessionPort`：创建、列出、附着和排队 session 工作；
- `KernelPort`：读取 context/liveness、应用 change、checkpoint 和执行研究 turn；
- `CapabilityRegistry`：描述、解析、prepare、execute、parse、finalize；
- `EnvironmentBroker`：解析 readiness 和不透明环境绑定；
- `ArtifactStore`：创建、验证、登记和有界读取 Artifact。

所有公共 request/result envelope 都使用版本化 JSON Schema。TypeScript 和 Python
实现只消费这些 schema，不互相 import 内部对象。

## App Server 组合

```text
App Server
  -> AgentRuntimePort
  -> KernelPort
  -> CapabilityRuntime
  -> MonitorPort
  -> Client adapters
```

默认安装注入 Pi Adapter。Core、Kernel 和 App Server 测试必须提供 Fake Runtime，
不要求 Pi、网络、凭证或真实模型服务。

当 Host 提供完整的 `KernelPort`（包含 `read_context` 和 `apply_change`）时，组合根可以
自动装配 `ComputeOrchestrator`。它复用 Capability Gateway 暴露的 Host `ArtifactStore`，
保证 Provider 输出登记和 Kernel Artifact 记录使用同一个存储。显式传入
`compute_orchestrator: null` 可以为不提供计算执行的部署关闭这条便捷路径。

Host 将 `compute_run` 和 `compute_cancel` 作为独立的 snake_case 操作暴露。取消只作用于
当前 Orchestrator 中仍活动的 Attempt，并通过 `AbortSignal` 传递给支持协作取消的 Provider；
Attempt 的最终状态仍由 Kernel 记录。Capability inventory 与环境 readiness 是独立的只读
Host 视图，不与 Provider 执行调用混在一起。

## 科研 Artifact 边界

普通 `read`、`write`、`bash` 可以产生 scratch 文件，但不能自动产生被接受的科研
Artifact。科研输入必须经过 `artifact_create`、验证和登记。登记后的 Artifact 才能
绑定 Compute Attempt，并由显式 Kernel change 提升为 Evidence。

因此水或甲醇这类简单系统可以在结构验证通过后直接生成；复杂或有歧义的结构必须先经过
候选和确认流程。

## 安装边界

Pi 是安装目录拥有的 content-addressed runtime，由锁定的 source revision、依赖锁和
patch digest 共同选择。生产启动拒绝安装目录外的 source。框架 release 不依赖系统中
已经安装的 Pi。

## 后果

- 新计算领域只需增加 Capability Provider 和 Profile，不需要修改 Agent Core 或
  Research Kernel；
- 将来可以用非 Pi Agent Runtime 复用 App Server 和 Kernel；
- Pi 版本变化被限制在一个 Adapter 和其测试中；
- 在大规模移动目录或增加领域功能前，必须先建立并验证公共合同。

## 工作区模式

工作区模式由 Host 在初始化工作区时选择，并在该工作区生命周期内保持不变。
Session 继承工作区模式；模型或工具不能通过 turn 参数修改模式。

工作区模式只决定生命周期和科研状态持久化策略，不再选择另一套 Capability
Registry。Manifest 显式记录两个 profile：

| 模式 | memory profile | execution profile | 科研生命周期 |
| --- | --- | --- | --- |
| `light` | `session` | `bounded` | 无 ResearchMap、Claim、Node、Attempt、Evidence、Monitor |
| `research` | `session` | `audited` | Kernel ResearchMap，加 Attempt、Evidence、Monitor |

`light` 只创建通用的输入、Artifact、运行、日志、临时和 Session 目录，使用普通
Agent Turn，并保留小型 Session Memory 与每次能力调用对应的 `LightRunStore` 记录。
Light run 包含输入/输出 manifest、环境身份、有界日志、资源限制和终态，但不会自动
成为 Claim、Finding 或 Evidence。用于能力执行的输入仍必须经过 Artifact 创建和验证。

`research` 配置除了通用目录，还创建 ResearchMap、Memory、Lifecycle、
Checkpoint、Node、Evidence、Monitor 和 Environment 目录，并以
`admission_pending` 生命周期状态和 genesis checkpoint 初始化一个空的合法
Kernel 状态。Host 通过独立的 `workspace_port_1` 准入操作推进状态；在仍处于
orient/准入阶段时，模型不能通过普通 change 操作直接创建第一个 Phase 或 Claim。

改变任务范围需要新建工作区或由 Host 显式 fork。轻量工作区导入的 Artifact
只能作为 candidate 或 input，不会自动变成 Research Evidence。同一个由 Host 装配的
Capability Gateway 服务两种 profile。Descriptor 可以声明只支持某一种或同时支持两种
模式；`light` 由 Host 施加有界资源和环境策略，`research` 在同一 Provider 外层增加
Kernel Attempt/Evidence 记录。Light run 必须通过显式的 Host/Kernel 操作才能提升到
research，不能因为进程成功就隐式提升。

模式同时决定回合合同：`light` Session 使用
`agent_turn_request`/`agent_turn_result`，`research` Session 使用
`research_turn_request`/`research_turn_result`。这由 Host/Core 策略决定，
不会根据工具名称临时推断。
