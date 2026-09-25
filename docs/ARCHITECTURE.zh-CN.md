# 架构

统一 Research Harness 生命周期的规范见 [ADR 0006](adr/0006-unified-research-harness-lifecycle.zh-CN.md)。

[English](ARCHITECTURE.md) | [简体中文](ARCHITECTURE.zh-CN.md)

TSPi 在 Pi 之上提供计算化学 skill 和运行时适配器。一个安装目录运行一个 Host，
服务 workspace root 下的直接子工作区；每个活动 session 由固定版本 Pi App Server 中
一个 `SessionWorker`/`AgentHarness` lane 拥有。终端、Phone、Monitor 都是客户端，不会
启动第二个 agent loop。Host 是 control plane，不是第二个 TUI。

## 组件职责

- `apps/app-server/` 提供 `tspi-host/1` control plane、安装级 Pi App Server owner、
  native remote client launcher、Monitor worker、browser adapter 和历史迁移工具。固定
  源码的 Pi worker 加载 TSPi tools、skills、hooks、策略和 system prompt。
- `services/tspi-link-relay/` 负责 TSPi Link 注册、配对、设备授权和不透明帧转发；它不拥有
  workspace/session/research，也不解析 Host RPC。
- `packages/ts-agent-kernel/ts_agent/` 管理 `ResearchMap`、引用完整性、验证和事务。
  计算控制面负责本地子进程的持久化生命周期，并通过配置好的
  `compute.run` 对 local 和 remote 使用同一套计算生命周期；统一的
  `compute.environments` 查询同时返回两类环境。渲染、报告和邮件仍由
  Skill/Plugin 工具提供。
- `extensions/pi/` 包含两层面向 Pi 的集成。legacy research、compute、review、artifact
  和 ExtensionAPI UI 适配器继续为直接 `pi` 启动保留；`extensions/pi/tui-package/`
  是仅在调用方用 `-e` 显式选择时才加载的 presentation facet。TSPi 启动器默认不选择
  presentation facet 或注册 TSPi 主题，因此 header、editor、命令目录、transcript 外壳和
  输入循环均由 Pi 自己提供。
  `extensions/server/` 包含包内 server 工具入口。App Server 只加载
  `extensions/server/extensions.json` 中经过 allowlist 和 SHA-256 校验的条目，不执行
  客户端提交的代码；worker 还统一加载 package skills、hooks、策略和 system prompt，
  所有 transport 使用同一份工具 runtime。
- `components/ts-web/` 是可选的只读浏览器客户端，直接渲染 Kernel 序列化的
  `ResearchMap`；浏览器控制通过显式启动的
  `TSPi --gateway` 适配器附着到已有 Host session，不会创建第二个 Worker。
- TS Phone 是独立 Flutter 客户端，通过 TSPi Link 连接 Host。

Pi App Server 独占 session directory、对话历史、模型状态、prompt loop 和 worker lane。
Host 负责路由、认证、幂等回执、scheduler lease 和客户端订阅。Pi 原生 TUI、Phone、
Monitor 都连接同一个 lane，因此共享 `read`、`write`、`bash` 和包内工具；传输方式不是
权限角色。

## 科学状态模型

工作区的规范状态是一个 `ResearchMap`。它以一个对象序列化为：

```text
research_map.json
nodes/<node_id>/          # Attempt / Artifact 等执行记录
inputs/                   # 工作区相对路径的输入 artifact
transactions.jsonl        # Kernel 变更历史
```

`ResearchMap` 是项目研究进展的规范对象，不是从多个 registry 临时拼接出来的
派生视图。它包含 `ResearchPhase`、`ResearchClaim`、`ResearchNode`、`Finding` 和
`Gate`，并维护它们之间的依赖、产出和目标引用。

Attempt 和 Artifact 不属于 ResearchMap 的科学事实集合。它们由 Compute/Workspace
Runtime 产生，但其稳定身份、digest、来源、lineage 和证据引用由 Research Kernel 的
Evidence Registry 管理。原始文件仍保存在 workspace 或对象存储中；Kernel 只保存
Artifact Manifest 和 Evidence Link，不把调度状态或文件内容直接解释成 Finding 或
Claim 结论。

```text
Compute Runtime -> Attempt -> Artifact Manifest
                              |
                              +-> Evidence Link -> Claim/Finding/Gate
```

Artifact 不是 Finding。Artifact 是可验证的数据对象，Evidence Link 表示它与科学对象
之间的 supports、contradicts、qualifies 或 derived_from 关系，Finding 则是 Root Agent
基于这些证据提交的科学陈述。大型日志、轨迹和图像不进入 ResearchMap 或模型上下文；
Agent 通过有界 manifest、摘要和按需 excerpt 读取它们。

### ResearchMap 与 Research Kernel

`ResearchMap` 是一个有类型的研究图。`ResearchClaim` 表示科学命题，`ResearchNode`
表示有界工作，`ResearchPhase` 只是可选的导航分组。Node 产生统一的 `Finding`，其中
`FactFinding` 表示确认后的事实，`IssueFinding` 表示问题、矛盾或风险。

```text
ResearchClaim -> ResearchNode -> FactFinding / IssueFinding
       ^               |                  |
       |               +------ Gate <-----+
       +----------- ClaimGate / NodeGate
```

`ResearchKernel` 负责加载、校验、事务提交和持久化 `ResearchMap`。`ResearchMap.to_dict()`
是给 TS Web 和 Root Agent 的规范序列化，不是第二个科学状态。Root Agent 选择问题、
方法、分支和停止条件；Skill 描述研究流程，Capability 描述可调用操作，Backend 实现
科学软件或执行器。Compute Environment 是绑定 Backend 的命名 `local` 或 `remote`
执行环境；Platform 只提供远端环境的传输和调度细节。工具成功不等于科学结论成立。

### 通用 Research Harness 分层与生命周期

Research Harness 是领域无关的研究运行时。反应机理、分子计算、数据分析、模拟或其他
研究领域都使用同一套对象和生命周期；领域差异只进入 Skill、Capability、Backend 和
Artifact schema，不能进入 Host 的调度判断或 Kernel 的 liveness 规则。

```text
Agent (唯一科学决策者)
  | 读取 bounded Research Context，选择方法、证据和停止条件
  v
Research Kernel (唯一科学状态权威)
  | ResearchMap: Claim / Node / Finding / Gate / Continuation
  | 校验、版本、ChangeSet、引用完整性
  v
Harness / Host (生命周期与权限控制)
  | turn admission、tool authority、幂等、恢复、follow-up、session 路由
  +--> Monitor (外部事件观察和 next_run 唤醒，不作科学判断)
  +--> Compute/Workspace Runtime (执行 Attempt、Artifact、环境和能力)
```

Research Memory 分为两层：workspace 中的 Durable Research Memory 保存完整 ResearchMap、
ChangeSet、Attempt、Artifact、事件和审计记录；每个 turn 由 Harness 从这些权威记录动态
组装有界的 `research.context`，只携带当前 focus Claim/Node、Gate 摘要、Continuation
摘要和运行时摘要；每类记录都有固定条数、文本长度和引用数量上限并返回截断标记，
任意 Continuation metadata 会缩减为 key，完整内容通过 detail/status 查询获取。Context
不是第二份科学状态，也不把完整历史或全部 Skill 正文复制进模型上下文。Skill 在
SessionWorker 创建时加载并缓存正文，但默认 prompt 只放 name、description 和 location；
只有显式调用 Skill 时才把正文注入当前 turn。Capability 和
Compute Environment 在方法选择或 launch 前按需查询。

运行时边界固定为：

```text
Research Memory（持久记录）
  -> ResearchMemoryService（面向 Host 的唯一 facade）
  -> ContextBuilder（确定性的有界投影）
  -> ContextPack（临时 turn 工作集）
  -> Prompt（ContextPack + 工具、Skill 元数据和指令）
```

`ResearchMemoryService` 不缓存第二份 ResearchMap，也不持久化 ContextPack。
`ContextPack.context_id` 和 provenance 标识其来源 revision，因此 Host 可以在状态变化
或重试后重新构造。语义写入仍只能通过 `research.change`、`research.strategy`、
`research.interpretation`、`research.continuation` 和 `research.checkpoint`；不提供会绕过
领域校验的通用 `memory.commit`。

Research Turn 的统一协议是：

```text
TRIGGER -> ORIENT(context) -> PLAN -> PREPARE -> EXECUTE
        -> WAIT/RECONCILE -> INTERPRET -> ADVANCE -> CHECKPOINT
```

每轮结束前，Agent 必须让 Kernel 的 liveness 落入以下之一：

- `required`：已登记明确的下一动作，由 Agent 在后续 turn 执行或处置；
- `waiting_external`：存在尚未终止的 Attempt/外部运行，等待 Monitor 的 `next_run`；
- `deferred`/`blocked`：明确记录原因和恢复条件；
- `terminal`：相关 Node/Claim/Gate 已完成或停止并写入结果。

如果 active Node 没有上述 disposition，Kernel 返回 `decision_needed`。Harness 只追加有
界 follow-up，要求 Agent 重新读取 bounded context 并登记 disposition；Harness 不选择
科学方法、不创建 Finding，也不把 `next_run` 当成新的研究指令。`research.liveness` 是
Monitor、Host 和 Agent 共用的生命周期诊断，`research.liveness`/`research.continuation` 是
Agent 已作出的下一步决定的持久化记录。
处于 `prepared` 的 Attempt 只有本地、提交前的绑定，因此仍是 Agent 的决策点，
而不是等待外部事件。只有已提交、排队中、运行中、完成但尚未解析或状态未知的
Attempt 才会让 scope 进入 `waiting_external`，直到 Host/Monitor 产生新证据。

所有公开工具都通过统一 contract 暴露：workspace/session 由 Harness context 绑定，模型
不能把请求重定向到另一个 root；`root` 只作为旧客户端的兼容断言。工具按 Read、Research
Write、Execution/Artifact、Advisory、External Side Effect 分类，并声明 authority、
replay/idempotency、所需 lifecycle phase 和输出 schema。Research Write 只能通过 Kernel
ChangeSet；Execution 工具只产生 Attempt/Artifact；Advisory 工具不拥有科学状态；Host
只负责执行边界和恢复。
Server extension loader 会在工具进入 Worker 前拒绝缺少完整 `label`、`description`、参数
schema、可执行函数以及四字段 Harness metadata contract 的工具。

工具工厂和传输适配器职责分离。`create*Tool()` 只定义领域行为，可以抛出带分类的错误，
本身不是 transcript 或 transport 边界。package-owned server extension 组合这些工厂；
legacy Pi 注册边界也使用同一个幂等 result wrapper，因此兼容传输不会暴露第二套 payload
契约。native `pi-session-worker` 在 Worker 边界应用 Harness adapter。成功结果使用
`tspi-tool-result/1` envelope；失败会先转换为带 `tspi-tool-error/1` 的普通 result，再由
native `after_tool` hook 或 legacy Pi `tool_result` hook 设置 `isError: true`，因此持久化
transcript 同时保留机器可读的失败信息和模型可见的错误状态。直接工厂测试可以绕过
adapter 调用领域工具；生产 Harness 流量必须经过上述某一个传输边界。

### NodeGate 与 ClaimGate

`NodeGate` 和 `ClaimGate` 是同一个 `Gate` 基类的两个特化类：

```text
Gate.criteria    = 冻结的收尾/评估标准
Gate.evaluations = 一次或多次评估记录
scope            = node | claim
```

NodeGate 判断 Node 是否可以关闭；ClaimGate 判断当前 Finding 是否足以支持或反驳
Claim。Gate 记录结果，但不会自动修改 Node 或 Claim；解释和状态变化必须由 Root Agent
通过 ChangeSet 明确提交。

## 独立科学能力与节点管理

`analysis.run` 通过按需能力目录派发 22 项版本化独立分析能力；对外目录由
`packages/ts-agent-kernel/ts_agent/compute/analysis.py` 组装，领域描述由
`packages/ts-agent-kernel/ts_agent/analysis/catalog.py` 定义，领域实现位于
`packages/ts-agent-kernel/ts_agent/analysis/`。结果绑定 Node、输入 digest、生成文件
和候选事实；选定事实通过已有 `research.change`
入口重算校验后登记。能力不选择下一科学步骤，不接受 Claim。化学网络使用带计量
的超边并允许有环，独立于研究 Node DAG。

`execution.dispatch` 的暂停/恢复回执位于操作层，不改变 Node 科学状态。共享锁协调暂停
与分析、提交 guard 的边界；在途作业仍可查看、收集和取消。报告和 TS Web 消费
规范 ResearchMap 数据。详见 [ADR 0002](adr/0002-independent-scientific-capabilities.md) 和
[能力运维文档](SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md)。

TS Web 直接渲染规范的 `ResearchMap` 序列化。Claim、Node、Finding、Gate 和依赖关系
都是同一个 map 的记录；浏览器不从后端日志或第二套 registry 重建科学状态，也不把
工具退出码直接当成结论或推断下一步行动。详见
[ADR 0003](adr/0003-minimal-research-kernel-and-gates.md)。

## App Server 生命周期

`ts-app-server-tspi.service` 调用 TSPi Host 入口，在 `.pi/app-server-host/` 创建安装级
状态，包括稳定 server ID、Host socket、format-4 session repository、bridge token、请求回执、
scheduler lease 和 Monitor 健康文件。`tspi.workspace-directory` 只暴露包含受支持
`workspace.json` 的直接子工作区。

`TSPi --workspace <name>` 先 bootstrap 工作区，再向 Host 请求 `session/list` 和
`session/create`/`session/resume`，最后把 Pi 官方 `ExperimentalClientTui` 直接连接到
返回的本地 descriptor。远程 TUI 负责 completion、渲染、输入循环和它支持的 slash
command，其中 `/resume` 只在当前 workspace 内切换；普通 Pi 的 `/new` 与 `/fork` 不会由
这个客户端暴露。Phone 通过 Host RPC，Monitor 通过 durable `next_run` entry 访问同一个
lane。workspace `.pi/sessions` 的 format-3 历史只读，显式 import 才能进入安装级 format-4。
`TSPI_HOST_BACKEND=ordinary` 仅是迁移/调试模式，不是 Harness fallback。

第一次执行 `TSPi --workspace <name>` 时，如果项目不存在，客户端会通过同一套经过校验
的 bootstrap 初始化它；Host 不会创建未命名项目，必须由客户端明确指定合法名称。

## TSPi Link

```text
TS Phone -- 出站 WSS --> TSPi Link Relay <-- 出站 WSS -- TSPi Host
                                                    |
                                                Unix socket
                                                    |
                              Pi App Server -> SessionWorker + AgentHarness
                                  ^                    ^             ^
                                  |                    |             |
                           Pi 原生 TUI              Phone         Monitor
```

两条网络连接都使用 `/v1/link` 和 `tspi-link.v1` WebSocket 子协议，但使用不同角色的
Bearer 凭据。短期 Host enrollment code 生成 Host 凭据；短期 Phone pairing code
生成可撤销的设备凭据。Relay 只把已授权设备映射到 Host，并原样转发带帧的
`tspi-host/1` NDJSON，不解析会话消息；这不是 Pi 实验性 remote 协议。

TSPi Link Relay 不拥有 workspace、session、transcript、工具或计算状态。Host 负责路由和
访问控制；Pi Harness worker 拥有 session、transcript、模型和工具。WSS 分别保护
两条网络链路，但 Link 1 不提供应用层端到端加密，因此 Relay 必须部署在可信基础设施上。

Link Relay 使用独立的 `install-link-relay.sh` 安装器，在公网或私有网络节点上单独安装和
升级。本地 TSPi 安装器只负责把当前 Host 注册到已有 Link Relay，不安装本地 Phone broker
或额外的本地传输服务。

## 浏览器控制

TS Web 默认只读，不拥有 Pi session。需要浏览器控制时，显式启动 loopback gateway：

```text
TSPi --gateway --workspace reaction-a --session-id <session-id> --port 8767
```

Gateway 只附着已经存在的 Host session，通过版本化 session-control 合约提供
snapshot、prompt、abort、queue 和 SSE 事件；request id 保证重试幂等，sequence
cursor 用于断线重连。它不启动第二个 App Server 或 Worker。

## 其他契约

ChangeSet 的操作定义位于 `ResearchKernel` 使用的 ResearchMap operation catalog；
`compute.run` 对 local/remote 使用相同的四个公开操作：

```text
launch   -> prepare, submit
inspect  -> status, optional tail
finalize -> collect, parse
cancel   -> cancel
```

右侧是 child runtime 的内部动作，不是额外的公开操作。对于
`execution_target.kind=local` 和 `execution_target.kind=remote`，Research Kernel
工作区始终是唯一规范存储：本地执行在 Attempt 的 execution 目录暂存输入并把输出
收集回工作区，远程目录只是临时执行镜像，TS Web 不需要访问远程文件系统。推荐的
`compute.toml` 将 local/remote 计算环境放在同一份 environments 目录中，每个环境在
backends 下绑定软件；只有 remote 环境增加 SSH/Torque 字段。`/compute` 和
`compute.environments` 使用同一份配置查询。
远程计算和产物记录使用显式 schema。TS Web 只读取工作区
文件，不拥有 Pi session。入口、skill、
扩展和测试位置与[英文架构](ARCHITECTURE.md)一致。

可用 user systemd 时，本地 worker 会进入独立的临时 service，因此重启 App Server Host
通常不会终止正在运行的本地计算；没有 user systemd 时使用进程组回退方案，重启父
service 前应先检查计算状态。

## Monitor 与 automation 生命周期

Monitor 是 App Server 的 control plane sibling worker，不是 Root session，也不是每个
workspace 的独立 daemon。一个安装级 App Server Host 启动一个 Monitor worker；worker
可以扫描配置 workspace root 下的多个直接子工作区。每个 workspace 只保存自己的
durable monitor records：

```text
operations/monitors/<monitor_id>/
  registration.json   # calc intent + intent digest + optional session binding
  state.json          # last observed semantic state
  events/<event_id>.json
  deliveries/<event_id>.json
```

Monitor registration、event 和 delivery 使用 `ts-compute-monitor/1`、
`ts-compute-monitor-event/1`、`ts-monitor-delivery/1` 合同。worker 的 tick 直接读取
Compute Kernel 的 durable status：`completed` 只表示程序或 scheduler 已结束，`parsed`
才表示收集和解析完成；`unknown` 保持不确定性。状态没有变化时不会重复产生事件。

事件 delivery 默认通过绑定 session 的 `next_run` 排队唤醒 Root，不打断当前推理。稳定
request id 为 `monitor:<event_id>`；session 不存在、workspace 不匹配或 App Server
重启时 delivery 保持 pending，可由后续 worker 恢复。Root 被唤醒后必须重新读取
`research.read`，再显式执行 `compute.run inspect`，并自行决定是否 `finalize` 或通过 `research.change`
写入 Finding/Gate/Node 状态。Monitor 不自动 finalize、不修改 ResearchMap、不做科学判断。

研究推进的 liveness 由 Kernel 校验的 continuation record 单独表示，不依赖 Monitor
是否还有新的状态摘要。`research.continuation` 可以查询记录，或使用 canonical 的
`set`/`resolve` 操作，为 Node、Claim、Gate 记录 `required`、`deferred`、`blocked`、
`completed` disposition；旧的 `set_*` 拼法只作为兼容 alias。ChangeSet 的审计字段属于
`research.change`，不混入生命周期请求。`required` 只记录 Root 已经选择的下一动作，不执行
动作，也不替 Root 选择科学结论。每次 run boundary，Host 最多为尚未解决的 required
record 追加三次 follow-up；Root 必须执行动作，或明确把记录置为 deferred、blocked、
completed。这样 parsed 之后即使没有新的 Monitor 事件，研究也能继续；阻塞或延期的研究
则保持静默且可审计。

Host 的 `monitor/event` 通知只是实时投影，不是持久化重放日志。Host 启动时会先建立已有
事件文件的游标，因此重启不会重复推送旧事件；Phone 重连时应通过 `monitor/status` 和
持久化 delivery outbox 恢复状态。

边界可以概括为：

```text
Workspace records <-> App Server Monitor worker -> Session next_run -> Root Agent
       ^                     |                         |
       |                     +-- user notification     +-- research.read / compute.run / research.change
       +-- Compute/remote durable status
```
