# ADR 0007：Research Agent Framework 边界

- 状态：新框架已接受
- 日期：2026-09-26
- 范围：新的 Research Agent Framework 实现

## 决定

新框架统一命名为 **Research Agent Framework**。本实现不承担 TSPi 兼容层；
TSPi 是基于 Pi SDK 的完整产品；Chemistry 是其中的一个 Extension Profile。

框架边界固定为：

```text
Contracts
  -> Agent Core
  -> Research State
  -> Native Compute Lifecycle（research-state runtime）
  -> App Server
  -> Pi SDK Runtime / TSPi Adapter
```

Agent Core 负责 TSPi 与 Pi 的合同、Context 和 session port，不重新实现 turn、模型请求、
工具调用、重试或恢复。上述 Agent Runtime 能力全部由 Pi SDK 提供。

Research State 是唯一的科研状态权威，负责 ResearchMap、Research Memory、Claim、
Node、Finding、Gate、Evidence Link 和生命周期决策。它不选择或执行科研后端。

Native Compute lifecycle 负责版本化 capability descriptor、calculation intent、Compute
Attempt 或 light execution scope、canonical Artifact、analysis 结果和 Environment 绑定。
它不能直接写入科研 Finding 或 Claim 状态。

App Server 是 TSPi 应用组合根，负责 Host RPC、workspace/session 绑定、权限、回执、恢复、
Monitor 和客户端适配。它只连接安装目录中的 Pi SDK Runtime。

Pi SDK 是唯一的 Agent Runtime。Pi import、experimental source、patch 校验、Pi
SessionWorker、Pi durable Harness 和 Pi 模型集成由 `agent-pi-adapter` 与 App Server 组合；
TSPi 不复制 Pi 的 Agent loop。框架不调用系统安装的 `pi` 命令，也不读取环境中的
Pi 配置。

所有协议标识使用下划线命名，例如 `research_turn_request`、
`research_turn_result`、`tool_result`、`capability_descriptor` 和
`artifact_manifest`。点号协议标识无效。

新实现不保留 TSPi runtime 兼容路径、旧工具名、点号协议别名或旧生命周期入口。迁移时
可以复用科研算法和数据格式，但必须重新放到新合同后面实现。

## Pi Session Port

最小的语言无关 Port 包括：

- `PiSessionPort`：TSPi 与 Pi Session 的内部连接边界；生产实现只有 Pi Adapter；
- `ModelPort`：描述模型并流式执行请求；
- `ContextPort`：从已准入输入构建有界、临时的 turn context；
- `MemoryPort`：读取和追加 session 级 Agent 记忆。它不是 ResearchMap 存储；
  workspace 级科研记忆写入必须经过 `ResearchStatePort`；
- `SessionPort`：创建、列出、附着和排队 session 工作；
- `ResearchStatePort`：读取 context/liveness、应用 change、checkpoint 和执行研究 turn；
- `NativeComputeLifecycle`：描述 capability、解析环境、物化 intent，执行、检查、finalize、cancel，并写入 canonical Artifact。

所有公共 request/result envelope 都使用版本化 JSON Schema。TypeScript 和 Python
实现只消费这些 schema，不互相 import 内部对象。

## App Server 组合

```text
App Server
  -> Pi SDK Runtime（唯一 Agent Runtime）
  -> ResearchStatePort
  -> Native Compute Lifecycle（research-state runtime）
  -> MonitorPort
  -> Client adapters
```

默认安装固定注入 Pi Adapter。Core、Research State 和 App Server 测试可以提供确定性的
Fake Session Port，但它不属于产品 Runtime。

Native Compute lifecycle 由 research-state runtime 唯一实现。组合根不再装配 JavaScript provider、Capability Gateway 或 Orchestrator；Native registry 负责 descriptor、intent、执行、解析和 canonical Artifact。`job_start/job_status/job_collect` 是唯一公开计算入口，取消和终态由 Research State 的持久记录控制。
## 科研 Artifact 边界

普通 `read`、`write`、`bash` 可以产生 scratch 文件，但不能自动产生被接受的科研
Artifact。科研输入必须经过 `artifact_create`、验证和登记。登记后的 Artifact 才能
绑定 Compute Attempt，并由显式 Research State change 提升为 Evidence。

因此水或甲醇这类简单系统可以在结构验证通过后直接生成；复杂或有歧义的结构必须先经过
候选和确认流程。

## 安装边界

Pi 是安装目录拥有的 content-addressed runtime，由锁定的 source revision、依赖锁和
patch digest 共同选择。生产启动拒绝安装目录外的 source。框架 release 不依赖系统中
已经安装的 Pi。

## 后果

- 新计算领域只需在 Python Native registry 和 backend contract 中增加能力，不需要修改
  Agent Core 或 Research State；
- 产品不提供非 Pi Agent Runtime 插件点；所有 Agent loop 变化都通过 Pi SDK 扩展点处理；
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
| `research` | `session` | `audited` | Research State ResearchMap，加 Attempt、Evidence、Monitor |

`light` 初始化时只创建通用的输入、Artifact、运行、日志、临时和 Session 目录，使用普通
Agent Turn；Native `job_start/job_status/job_collect` 会在 `nodes/<execution_scope>/attempts/` 下物化
operational execution scope，并写入 canonical workspace Artifact。
它不会创建 ResearchMap Claim、Finding、Evidence、Attempt 或 Monitor。

`research` 配置除了通用目录，还创建 ResearchMap、Memory、Lifecycle、
Checkpoint、Node、Evidence、Operations 和 Environment 目录，并以
`admission_pending` 生命周期状态和 genesis checkpoint 初始化一个空的合法
Research State 状态。Host 通过独立的 `workspace_port_1` 准入操作推进状态；在仍处于
orient/准入阶段时，模型不能通过普通 change 操作直接创建第一个 Phase 或 Claim。

改变任务范围需要新建工作区或由 Host 显式 fork。轻量工作区导入的 Artifact
只能作为 candidate 或 input，不会自动变成 Research Evidence。两种 profile 使用同一套 Native `job_start/job_status/job_collect` 生命周期。Descriptor 可以声明只支持某一种
或同时支持两种模式；`light` 使用 operational execution scope，`research` 增加 Research State
Attempt/Evidence 记录。Light 到 research 的提升必须经过显式 Host/Research State 操作，不能因为
进程成功就隐式提升。

模式同时决定回合合同：`light` Session 使用
`agent_turn_request`/`agent_turn_result`，`research` Session 使用
`research_turn_request`/`research_turn_result`。这由 Host/Core 策略决定，
不会根据工具名称临时推断。
