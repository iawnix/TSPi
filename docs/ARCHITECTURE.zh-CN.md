# 架构

统一 Research Harness 生命周期的规范见 [ADR 0006](adr/0006-unified-research-harness-lifecycle.zh-CN.md)。

[English](ARCHITECTURE.md) | [简体中文](ARCHITECTURE.zh-CN.md)

TSPi 在 Pi 之上提供计算化学 skill 和运行时适配器。一个安装目录运行一个 Agent Server；
其中 Host 是 API、会话和事务宿主，Root Agent/Harness 负责真正的 prompt loop、工具和模型。
每个活动 session 由固定版本 Pi App Server 中一个 `SessionWorker`/`durable Harness` lane
拥有。终端、Phone、Monitor 都是客户端，不会启动第二个 agent loop。Host 是 Agent 的宿主层，
不是另一个 Root Agent，也不是第二个 TUI。

## 组件职责

- `apps/app-server/` 提供 Agent Server：`tspi-host/1` API、Root Agent session 宿主、统一
  Host HTTP adapter、安装级 Pi App Server/Harness owner、native remote client
  launcher、Monitor worker、browser adapter 和历史迁移工具。固定源码的 Pi worker 加载
  TSPi tools、skills、hooks、策略和 system prompt。
- `services/tspi-link-relay/` 负责 TSPi Link 注册、配对、设备授权和不透明帧转发；它不拥有
  workspace/session/research，也不解析 Host RPC。
- `packages/research-state/` 管理规范 `ResearchMap`、admission、引用完整性、验证、revision 和事务；`packages/research-memory/` 构建 bounded context 与 session projection；`packages/job-runtime/` 执行本地和远端 Job，`packages/tspi-runtime/` 将其回执、观察与收集产物接入 Research State。共享 Link 协议与 backpressure codec 位于 `packages/tspi-link/`，`services/tspi-link-relay/` 只负责服务组合。
- `extensions/` 包含可安装的 Skill、科学脚本、注册验证器和验收 profile。科学计算和分析由 Skill 脚本通过通用 Job 执行，报告排版与邮件由 native bash 调用 Skill helper。扩展 manifest 仍支持 provider 元数据发现，这些库存描述不负责派发科学执行。包内核心 server tool 装配位于 `apps/app-server/server-tools/`。
- `packages/agent-ui/` 仅包含 Native client facet 所需的少量 presentation helper。
  直接 ExtensionAPI 适配器及其公共入口已经移除；启动器和 Native Pi Worker 不会加载
  旧的 ExtensionAPI 路径。
  `apps/app-server/server-tools/` 是唯一的包内 server 工具入口。App Server 只加载经过 allowlist 和
  SHA-256 校验的条目，不执行客户端提交的代码；worker 还统一加载 package skills、hooks、
  策略和 system prompt，所有 transport 使用同一份工具 runtime。
- `components/ts-web/` 是可选的只读浏览器客户端，直接渲染 Research State 序列化的
  `ResearchMap`；浏览器控制通过显式启动的
  `apps/app-server/tspi-browser-gateway.mjs` 适配器附着到已有 Host session，不会创建第二个 Worker。
- TS Phone 是独立 Flutter 客户端，通过 TSPi Link 连接 Host。

Pi App Server/Harness 独占 session directory、对话历史、模型状态、prompt loop 和 worker
lane；Host 是同一个 Agent Server 中对外的 API、路由、认证、幂等回执、scheduler lease、
事务和客户端订阅层。Pi 原生 TUI、Phone、Monitor 都连接同一个 lane，因此共享 `read`、
`write`、`bash` 和包内工具；传输方式不是权限角色。

Host RPC 与底层传输解耦。安装内客户端使用私有 Unix socket；远程终端客户端可以通过
SSH 启动 `tspi-host-proxy`，由 proxy 将 stdin/stdout 字节转发到远端 Host 与 Pi App
Server socket；Phone 继续通过 TSPi Link 的 WSS Relay。三种方式都使用同一份
`tspi-host/1` NDJSON，不会创建第二个 Agent lane。

远程 Host 所在机器是 workspace、SQLite durable session、Research Memory 和 workspace
lock 的唯一权威位置。TSPi 不使用实时双向 rsync 同步工作区；rsync 或其它批量复制工具只
能用于显式的远程作业文件操作；artifact 注册仍然独立于传输方式。

## 科学状态模型

每个 research workspace 只有一套文件系统 `ResearchMap` context 与持久生命周期投影：

```text
workspace_manifest.json     # 不可变 identity、mode、root 与 admission 状态
research_map/context.json   # ResearchMap 科学状态权威文件
lifecycle/liveness.json     # 生命周期与 decision-needed 投影
memory/index.json           # 有界 memory 投影
nodes/<node_id>/            # 可选的 Node 工作文件
runs/jobs/<job_id>/         # Job 暂存输入、回执、日志和输出
artifacts/<artifact_id>/    # 已登记的 payload 和 manifest
inputs/                   # 工作区相对路径的输入 artifact
operations/               # turn、monitor 和 execution receipts
```

规范科学记录位于 `research_map/context.json`，包括 phase、claim、node、finding、gate、
requirement、Attempt、Artifact 和 evidence link。`research.map` 将这些记录投影为客户端
使用的 `research-map/1` 文档。Research State 通过合同和 ChangeSet 验证、修改规范 JSON 记录。

Attempt 记录 Job 执行，Artifact 描述收集或导入的材料。其稳定身份、digest、来源、
lineage 和证据引用由 Research State 与 Artifact Store 管理。原始文件保存在 workspace；
Research State 保存有界的 Artifact 记录与 Evidence Link，不把调度状态或文件内容直接解释成 Finding 或
Claim 结论。

```text
Job Runtime -> Attempt -> Artifact Manifest
                              |
                              +-> Evidence Link -> Claim/Finding/Gate
```

Artifact 不是 Finding。Artifact 是可验证的数据对象，Evidence Link 表示它与科学对象
之间的 supports、contradicts、qualifies 或 derived_from 关系，Finding 则是 Root Agent
基于这些证据提交的科学陈述。大型日志、轨迹和图像不进入 ResearchMap 或模型上下文；
Agent 通过有界 manifest、摘要和按需 excerpt 读取它们。

### ResearchMap 与 Research State

`ResearchMap` 是具有明确记录种类的研究图。Claim 表示科学命题，Node 表示有界工作，
Phase 是可选的导航分组。Finding 使用 `kind: fact` 记录观察，使用 `kind: issue` 记录
问题、矛盾或风险；状态和所引用证据是独立字段。

新 Claim 从 `proposed` 开始；科学状态由 `assess_claim` 记录理由和已登记证据后更新。
导入数据和文献可作为证据，不要求新增 Job。当前采用的评估绑定证据版本与所需 ClaimGate，
投影显示 `current`、`needs_review` 或 `not_assessed`，不会把历史状态自动升级为已核实评估。
证据或 ClaimGate 变化可先提交，再另行评估；`needs_review` 阻止 terminal 收尾，不冻结独立工作。

```text
Claim -> Node -> Finding (kind: fact | issue)
       ^               |                  |
       |               +------ Gate <-----+
       +----------- ClaimGate / NodeGate
```

文件系统 Research State 负责加载、校验、事务提交和持久化规范 workspace projection，
由 research-state runtime 唯一实现；Node App Server 只提供传输 bridge 和语言无关的 port。
map-shaped context projection 是给 TS Web 和 Root Agent 的规范序列化，不是第二个科学状态。
Root Agent 选择问题、方法、分支和停止条件；Skill 描述研究流程并构造已安装科学软件的
命令。命名的 Job 环境选择本地或远端执行、软件配置以及所需的传输和调度设置。
工具成功不等于科学结论成立。

### 通用 Research Harness 分层与生命周期

Research Harness 是领域无关的研究运行时。反应机理、分子计算、数据分析、模拟或其他
研究领域都使用同一套对象和生命周期；领域差异只进入 Skill、科学脚本、验证器和
Artifact schema，不能进入 Host 的调度判断或 Research State 的 liveness 规则。

```text
Agent (唯一科学决策者)
  | 读取 bounded Research Context，选择方法、证据和停止条件
  v
Research State (唯一科学状态权威)
  | ResearchMap: Claim / Node / Finding / Gate / LifecycleAction
  | 校验、版本、ChangeSet、引用完整性
  v
Harness / Host (生命周期与权限控制)
  | turn admission、tool authority、幂等、恢复、follow-up、session 路由
  +--> Monitor (外部事件观察和 next_run 唤醒，不作科学判断)
  +--> Job Runtime 与 Artifact Store (执行与收集材料)
```

Research Memory 分为两层：workspace 中的 Durable Research Memory 保存完整 ResearchMap、
ChangeSet、Attempt、Artifact、事件和审计记录；每个 turn 由 Harness 从这些权威记录动态
组装有界的 `research.context`，只携带当前 focus Claim/Node、Gate 摘要、LifecycleAction
摘要和运行时摘要；每类记录都有固定条数、文本长度和引用数量上限并返回截断标记，
任意 LifecycleAction metadata 会缩减为 key，完整内容通过 State 查询获取。Context
不是第二份科学状态，也不把完整历史或全部 Skill 正文复制进模型上下文。Skill 在
SessionWorker 创建时加载并缓存正文，但默认 prompt 放 name、description、location，以及两个核心系统 Skill 的 `system` scope 标记；
只有显式调用 Skill 时才把正文注入当前 turn。Compute Environment 在方法选择或 launch 前按需查询。

每次模型请求携带最新状态，放入仅供本次请求使用的 `tspi_research_context` 系统区段，
不追加用户消息、不写入会话历史，也不启动新轮次。`continue_required` 不要求再次恢复。
焦点视图补充策略和 Attempt 引用节点及其依赖的简要记录，并明确“未展示不等于不存在”。

Worker 从持久会话记录识别同一研究 revision 下连续读取 context/liveness、提交 checkpoint
的控制循环：连续 6 次提醒，12 次则在继续生成或压缩前停止请求。更换 checkpoint 名称和
查询 limit 不会清零计数；其他工作或证据调用、revision 变化、真实用户输入会打断计数。
该保护只检测这类控制循环，不判断科学进展、不取消 Job、不改写 Research State。
自动续跑入口检查同一记录，避免立即重启已停止的循环。

通用 Job Runtime 是执行边界。Skill 构造程序 argv、输入文件、预期输出、解析说明和方法
metadata；`job_start` 接受该有边界 argv，并统一支持本地与远端执行。Skill 与 Job Runtime
之间没有科学 provider registry 或 capability descriptor 门禁。Preflight 检查选定的命名环境，
并把配置记录在 Job metadata 中。light execution scope 和 research Attempt 都通过同一控制路径
写入 canonical workspace Artifact，不再存在第二套 ArtifactStore。

运行时边界固定为：

```text
Research Memory（持久记录）
  -> ResearchMemoryService（面向 Host 的唯一 facade）
  -> ContextBuilder（确定性的有界投影）
  -> ContextPack（临时 turn 工作集）
  -> Prompt（ContextPack + 工具、Skill 元数据和指令）
```

Native worker 通过运行时命令边界读取 `research.context`。Pi 管理会话历史，Research
State 管理工作区科学记录及其 memory 投影。刷新有界上下文不会创建另一份状态存储或
会话宿主。

`ResearchMemoryService` 不缓存第二份 ResearchMap，也不持久化 ContextPack。
`ContextPack.revision` 和 provenance 标识其来源 revision，因此 Host 可以在状态变化
或重试后重新构造。新的语义写入只能通过 `research_change`、`research_strategy`、
`research_interpretation` 和 `research_checkpoint`；后者写入规范 turn checkpoint。不提供会
绕过领域校验的通用 `memory.commit`。

Research Turn 的统一协议是：

```text
TRIGGER -> ORIENT(context) -> PLAN -> PREPARE -> EXECUTE
        -> WAIT/RECONCILE -> INTERPRET -> ADVANCE -> CHECKPOINT
```

每轮结束前，Agent 必须调用 `research_checkpoint`，登记一种当前 disposition：
`continue_required`、`waiting_external`、`deferred`、`blocked`、`terminal` 或
`user_input_required`。`continue_required` 表示 Agent 已经选择了下一 turn 的明确动作。
生命周期动作通过规范的 ChangeSet 操作管理。`research.liveness` 只是有界的生命周期诊断
投影，不是持久化下一步，也不负责关闭 turn。

如果 active Node 没有合法 disposition，Research State 返回 `decision_needed`。如果当前 focus
已经有 active StrategyPlan，liveness 还会返回 `execution_ready=true`，Host 可以在同一
turn 放行该计划对应的 prepare/execute；Agent 仍必须在结束 turn 前写入 checkpoint。
没有 `execution_ready` 时，Host 只放行读取、规划、解释和 checkpoint 修复。Harness 只追加
有界 follow-up，要求 Agent 重新读取 bounded context 并通过 checkpoint 登记 disposition；
Harness 不选择科学方法、不创建 Finding，也不把 `next_run` 当成新的研究指令。
prepared request 尚未启动执行。处于 `started`、`running` 或 `unknown` 的 Attempt
可以让对应 scope 进入 `waiting_external`；Job 完成后，研究仍需显式收集、解释和当前验收。

`research.liveness` 只返回规范的 `continue_required` 记录。

所有公开工具都通过统一 contract 暴露：workspace/session 由 Harness context 绑定，模型
不能把请求重定向到另一个 root；`root` 只作为旧客户端的兼容断言。工具按 Read、Research
Write、Execution/Artifact、Advisory、External Side Effect 分类，并声明 authority、
replay/idempotency、所需 lifecycle phase 和输出 schema。Research Write 只能通过 Research State
ChangeSet；Execution 工具只产生 Attempt/Artifact；Advisory 工具不拥有科学状态；Host
只负责执行边界和恢复。
Server extension loader 会在工具进入 Worker 前拒绝缺少完整 `label`、`description`、参数
schema、可执行函数以及四字段 Harness metadata contract 的工具。

工具工厂和传输适配器职责分离。`create*Tool()` 只定义领域行为，可以抛出带分类的错误，
本身不是 transcript 或 transport 边界。package-owned server extension 组合这些工厂；
Native `pi-session-worker` 在 Worker 边界应用 Harness adapter。成功结果使用
`tspi-tool-result/1` envelope；失败会先转换为带 `tspi-tool-error/1` 的普通 result，再由
Native `after_tool` hook 设置 `isError: true`，因此持久化 transcript 同时保留机器可读的
失败信息和模型可见的错误状态。直接工厂测试可以绕过 adapter 调用领域工具；生产 Harness
流量必须经过 Native server-extension 边界。

### NodeGate 与 ClaimGate

NodeGate 和 ClaimGate 是通过 `scope` 区分的 Gate 记录：

```text
Gate.criteria    = 版本化的收尾/评估标准
Gate.evaluations = 一次或多次评估记录
scope            = node | claim
```

NodeGate 判断 Node 是否可以关闭；ClaimGate 判断当前 Finding 是否足以支持或反驳
Claim。Gate 记录结果，但不会自动修改 Node 或 Claim；解释和状态变化必须由 Root Agent
通过 ChangeSet 明确提交。

## 独立科学能力与节点管理

`artifact_derive` 只记录派生描述，不派发分析或生成科学输出。科学脚本位于 Domain Skill，
通过通用 Job Runtime 执行；真实输出连同输入摘要和来源登记为 Artifact。已注册验证器列在
extension manifest 中，通过 `job_start` 调用，不需要分析 capability catalog。

化学扩展提供分子准备、Gaussian/xTB/CF22D runner、报告生成与注册验证器。有限的 mapped
Diels–Alder 路径实现 RDKit 候选、Gaussian QST2/Freq 和双向 IRC 输入准备，并分开检查映射、
成键振动模式与端点连通性。验证消费绑定的真实收集产物，不表示穷尽机理搜索或保证真实
Gaussian 收敛。支持结构、输出格式和验证限制见 candidate-generation Skill。其他已安装科学命令可在核实实际输入输出合同后使用通用 Job。
执行结果不会隐式更新 Claim。

TS Web 直接渲染规范的 `ResearchMap` 序列化。Claim、Node、Finding、Gate 和依赖关系
都是同一个 map 的记录；浏览器不从后端日志或第二套 registry 重建科学状态，也不把
工具退出码直接当成结论或推断下一步行动。详见
[ADR 0003](adr/0003-minimal-research-state-and-gates.md)。

## App Server 生命周期

`ts-app-server-tspi.service` 调用 TSPi Host 入口，在 `var/state/host/` 创建安装级
状态，包括稳定 server ID、Host socket、SQLite durable session repository、请求回执、
scheduler lease 和 Monitor 健康文件。`tspi.workspace-directory` 只暴露包含受支持
`workspace_manifest.json` 及规范研究状态三元组的 workspace。

`ResearchAgent --workspace <name>` 先 bootstrap 工作区，再向 Host 请求 `session/list` 和
`session/create`/`session/resume`，最后把 Pi 官方 `ExperimentalClientTui` 直接连接到
返回的本地 descriptor。远程 TUI 负责 completion、渲染、输入循环和它支持的 slash
command，其中 `/resume` 只在当前 workspace 内切换；独立 Pi 的会话命令不会由这个客户端
暴露。Phone 通过 Host RPC，Monitor 通过 durable `next_run` entry 访问同一个
lane。workspace `.pi/sessions` 不属于受支持的 Native 运行时边界，不会被导入或恢复。
`TSPI_HOST_BACKEND` 必须为 `harness`；已退役的 ordinary-Pi 后端会直接拒绝。

第一次执行 `ResearchAgent --workspace <name>` 时，如果项目不存在，客户端会通过同一套经过校验
的 bootstrap 初始化它；Host 不会创建未命名项目，必须由客户端明确指定合法名称。

## TSPi Link

```text
TS Phone -- 出站 WSS --> TSPi Link Relay <-- 出站 WSS -- TSPi Host
                                                    |
                                                Unix socket
                                                    |
                              Pi App Server -> SessionWorker + durable Harness
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

```bash
node apps/app-server/tspi-browser-gateway.mjs \
  --connect unix:///run/user/$UID/tspi/<server-id>.sock \
  --workspace /absolute/workspaces/reaction-a \
  --session-id <session-id> --port 8767
```

Gateway 只附着已经存在的 Host session，通过版本化 session-control 合约提供
snapshot、prompt、abort、queue 和 SSE 事件；request id 保证重试幂等，sequence
cursor 用于断线重连。它不启动第二个 App Server 或 Worker。

## 其他契约

ChangeSet 的操作定义位于文件系统 Research State 使用的 ResearchMap operation catalog；
通用 Job 对 local/remote 使用相同的公开工具：

```text
job_start     -> 暂存输入、提交
job_status    -> 查看执行状态与有界输出
job_collect   -> 收集声明产物、生成结果回执
job_cancel    -> 请求取消
job_reconcile -> 协调确认不确定的执行状态
```

科学解析与解释由 Skill 显式完成，Job 的 `platform` 选择安装级环境。Research State
工作区始终是唯一规范存储：本地执行在 `runs/jobs/<job_id>/` 暂存输入并把输出
收集回工作区，远程目录只是临时执行镜像，TS Web 不需要访问远程文件系统。推荐的
`job.toml` 将 local/remote 计算环境放在同一份 environments 目录中，每个环境在
backends 下绑定软件；只有 remote 环境增加 SSH/Torque 字段。`job_probe` 检查所选平台，
不证明科学方法就绪；方法检查使用配置的命令和 Skill helper。
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
  binding.json        # Job/Attempt/session 绑定、摘要和最近观察
  events/<event_id>.json
  deliveries/<event_id>.json
```

Monitor binding、event 和 delivery 使用 `ts-job-monitor/1`、`ts-job-monitor-event/1`、
`ts-job-monitor-delivery/1` 合同。worker 的 tick 读取 Job Runtime 状态并记录对应 Attempt
观察。执行终态和 `unknown` 可以产生唤醒事件；收集和科学解释仍需显式完成。状态没有
变化时不会重复产生事件，配置的排队等待阈值首次超出除外。

事件 delivery 默认通过绑定 session 的 `next_run` 排队唤醒 Root，不打断当前推理。稳定
request id 为 `job-wake:<event_id>`；session 不存在、workspace 不匹配或 App Server
重启时 delivery 保持 pending，可由后续 worker 恢复。Root 被唤醒后必须重新读取
`research_read`，通过 `job_status` 检查 Job、通过 `job_collect` 收集证据，再决定如何解释
和修改 Research State。Monitor 记录执行观察，不收集输出、不更新科学结论，也不发送用户通知。

研究推进的 liveness 是独立于 Monitor 观察的诊断投影。turn boundary 通过
`research_checkpoint` 持久化 Agent 的 disposition。它是规范 checkpoint；生命周期动作通过
规范 ChangeSet 操作管理。ChangeSet 的审计字段属于 `research_change`。每次 run boundary，
Host 遵守 checkpoint 结果和有界接续策略，不会替 Agent 选择方法。这样收集完成后即使
没有新的 Monitor 事件，研究也能继续；阻塞或延期的研究则保持静默且可审计。

Host 的 `monitor/event` 通知只是实时投影，不是持久化重放日志。Host 启动时会先建立已有
事件文件的游标，因此重启不会重复推送旧事件；Phone 重连时应通过 `monitor/status` 和
持久化 delivery outbox 恢复状态。

边界可以概括为：

```text
Workspace records <-> App Server Monitor worker -> Session next_run -> Root Agent
       ^                     |                         |
       |                                               +-- research_read / job_status / job_collect / research_change
       +-- Job Runtime durable status
```


## 有来源的交付要求与当前验收

`research-requirements/1` 保存用户交付要求，不替代科学 Claim。Host 从真实 Pi 用户提交保存
来源，Monitor 和 State 接续属于内部输入。已安装的版本化 profile 定义有限验收检查；要求
绑定原文、约束、输入和贡献 Node，通过实际 result receipt 派生是否满足。原文覆盖仍是
Agent 判断，保存消息不等于形式化证明已抽取所有自然语言要求。

Gate 修改不能降低 requirement 的原始检查。阶段 Node 可以先完成，完成约定分析后 Claim
仍可无结论。停止保留未履行要求，需要真实取消来源或匹配范围的失败证据；新 Attempt
会使旧停止决定过期。已完成交付保留当时消费版本；新证据可以使当前验收过期并阻止新成功。

准入、liveness 和完成共用 dependency_evaluation，支持 completed 或 finished 条件。
交付声明消费的要求、Artifact 或前置 Node；邮件 prepare 绑定事件和当前状态，send 再次核对。
sent/unknown 回执继续遵循既有幂等与不确定性规则。

受管 Job 引用 pN 和 Artifact 引用 aN 是持久精确索引。事务日志 v2 首次迁移扫描历史，
以后只恢复未完成提交。升级前停止全部旧写入进程，已升级工作区不可直接降级，详见
[迁移说明](MANAGED_REFERENCES_AND_TRANSACTION_RECOVERY.zh-CN.md)。

State 桥接中断时，只允许本地 read/system_prompt 用于诊断，副作用仍需当前 State 准入。
首次用户来源保存失败会阻止该输入开始；后续 yield 检查失败时保留诊断答复，不制造 checkpoint
或自动接续。


已清理的平行框架、状态模型和旧执行实现见 [ADR 0010](adr/0010-retire-parallel-runtimes.zh-CN.md)。
发行检查会拒绝这些旧实现重新进入安装包。现行工作区和 Job 回执继续使用原合同；
已删除的旧导入 facade 不保留兼容 shim。
