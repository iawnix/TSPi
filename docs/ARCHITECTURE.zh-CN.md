# 架构

[English](ARCHITECTURE.md) | [简体中文](ARCHITECTURE.zh-CN.md)

TSPi 在 Pi 之上提供计算化学 skill 和运行时适配器。一个安装目录只运行一个原生
Pi App Server Host，由它服务配置的 workspace root 下的所有直接子工作区；不再需要单独
的 TS Phone broker 或每个工作区一个 service。

## 组件职责

- `apps/app-server/` 启动 Pi 原生 App Server 和 session worker。
- `services/tspi-link-relay/` 负责 TSPi Link 的 Host 注册、手机配对、设备授权和不透明字节
  转发；它不提供 App Server 或研究 API。
- `packages/ts-agent-kernel/ts_agent/` 管理 `ResearchMap`、引用完整性、验证和事务。
  计算控制面负责本地子进程的持久化生命周期，并通过配置好的
  `ts_calc` 对 local 和 remote 使用同一套计算生命周期；统一的
  `compute.environments` 查询同时返回两类环境。渲染、报告和邮件仍由
  Skill/Plugin 工具提供。
- `extensions/pi/` 包含两层面向 Pi 的集成。legacy research、compute、review、artifact
  和 ExtensionAPI UI 适配器继续为直接 `pi` 启动保留；`extensions/pi/tui-package/`
  是 `ExperimentalClientTui` 使用的原生 TSPi presentation facet，通过 Pi 的
  `PresentationLayout` service 提供 Header、Footer、Editor、theme 渲染和 `/runs`
  浏览器。`TSPi --workspace` 会加载后者，但不会加载 legacy ExtensionAPI UI 适配器。
  `extensions/server/` 包含包内 server 工具入口。App Server 只加载
  `extensions/server/extensions.json` 中经过 allowlist 和 SHA-256 校验的条目，不执行
  客户端提交的代码。
- `components/ts-web/` 是可选的只读浏览器客户端，直接渲染 Kernel 序列化的
  `ResearchMap`；浏览器控制通过显式启动的
  `TSPi --gateway` 适配器附着到已有 Host session，不会创建第二个 Worker。
- TS Phone 是独立 Flutter 客户端，通过 TSPi Link 连接 App Server。

App Server 独占 session directory、对话历史、模型状态、prompt 操作和工作区 Root
锁；本地 TUI 与 TS Phone 连接同一个 owner，并共享 `read`、`write`、`bash` 和全部
包内工具，客户端传输方式不是权限角色。Worker 会加载包中对模型可见的 skill、原生
system prompt 和经过验证的 server extension inventory。该 inventory 会写入
`sys_prompt` provenance，客户端可以审计本次会话使用的工具集合。

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

`ts_analyze` 通过按需能力目录派发 22 项版本化独立分析能力；对外目录由
`packages/ts-agent-kernel/ts_agent/compute/analysis.py` 组装，领域描述由
`packages/ts-agent-kernel/ts_agent/analysis/catalog.py` 定义，领域实现位于
`packages/ts-agent-kernel/ts_agent/analysis/`。结果绑定 Node、输入 digest、生成文件
和候选事实；选定事实通过已有 `ts_change`
入口重算校验后登记。能力不选择下一科学步骤，不接受 Claim。化学网络使用带计量
的超边并允许有环，独立于研究 Node DAG。

`ts_dispatch` 的暂停/恢复回执位于操作层，不改变 Node 科学状态。共享锁协调暂停
与分析、提交 guard 的边界；在途作业仍可查看、收集和取消。报告和 TS Web 消费
规范 ResearchMap 数据。详见 [ADR 0002](adr/0002-independent-scientific-capabilities.md) 和
[能力运维文档](SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md)。

TS Web 直接渲染规范的 `ResearchMap` 序列化。Claim、Node、Finding、Gate 和依赖关系
都是同一个 map 的记录；浏览器不从后端日志或第二套 registry 重建科学状态，也不把
工具退出码直接当成结论或推断下一步行动。详见
[ADR 0003](adr/0003-minimal-research-kernel-and-gates.md)。

## App Server 生命周期

`ts-app-server-tspi.service` 调用 TSPi 的内部 Host 入口，在 `.pi/app-server-host/`
创建安装级 Host 状态并写入一个稳定 UUID，
获取 Host Root 锁并启动 Pi App Server。`.pi/app-server-host/sessions/` 保存全部会话；
`.pi/app-server-host/workspace/` 只是 Host 的私有 Pi 控制 cwd，不是研究项目。
每个会话创建时带有配置的 workspace root（默认 `<install>/workspaces`）下项目的 cwd，
并由 `TSPI_WORKSPACE_ROOT` 限制。
`tspi.workspace-directory` 只暴露包含受支持 `workspace.json` 的直接子工作区。

`TSPi --workspace <name>` 是连接 Host 的 Pi 原生 TUI 客户端，并在创建会话时传递
`TSPI_SESSION_CWD`。TS Phone 通过同一组 service 列出或创建项目，并创建或切换会话，
无需为每个项目再次连接或启动 Host。启动器通过原生 App Server 入口进入选定项目，
不再维护第二套工作区启动路径。若配置的 systemd service 尚未运行，终端启动器会通过
systemd 启动它并有限等待唯一 Host 的 Unix socket；不会回退为第二个前台 Host。服务
scope 可以是 user 或 system；scope 为 none 时禁用受管 Host。

第一次执行 `TSPi --workspace <name>` 时，如果项目不存在，客户端会通过同一套经过校验
的 bootstrap 初始化它；Host 不会创建未命名项目，必须由客户端明确指定合法名称。

## TSPi Link

```text
TS Phone -- 出站 WSS --> TSPi Link Relay <-- 出站 WSS -- TSPi Host
                                                    |
                                                Unix socket
                                                    |
                                              Pi App Server
```

两条网络连接都使用 `/v1/link` 和 `tspi-link.v1` WebSocket 子协议，但使用不同角色的
Bearer 凭据。短期 Host enrollment code 生成 Host 凭据；短期 Phone pairing code
生成可撤销的设备凭据。Relay 只把已授权设备映射到 Host，并原样转发 Pi App Server
字节流，不解析其中的会话消息。

TSPi Link Relay 不拥有 workspace、session、transcript、工具或计算状态；这些仍由 App Server
独占。WSS 分别保护两条网络链路，但 Link 1 不提供应用层端到端加密，因此 Relay 必须
部署在可信基础设施上。

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
`ts_calc` 对 local/remote 使用相同的四个公开操作：

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
`ts_state`，再显式执行 `ts_calc inspect`，并自行决定是否 `finalize` 或通过 `ts_change`
写入 Finding/Gate/Node 状态。Monitor 不自动 finalize、不修改 ResearchMap、不做科学判断。

边界可以概括为：

```text
Workspace records <-> App Server Monitor worker -> Session next_run -> Root Agent
       ^                     |                         |
       |                     +-- user notification     +-- ts_state / ts_calc / ts_change
       +-- Compute/remote durable status
```
