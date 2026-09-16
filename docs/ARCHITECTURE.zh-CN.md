# 架构

TSPi 在 Pi 之上提供计算化学 skill 和工作流扩展。一个安装目录只运行一个原生
Pi App Server Host，由它服务 `workspaces/` 下的所有直接子工作区；不再需要单独
的 TS Phone broker 或每个工作区一个 service。

## 组件职责

- `apps/app-server/` 启动 Pi 原生 App Server 和 session worker。
- `packages/ts-agent-kernel/ts_agent/` 管理科学契约、工作区状态、引用完整性、验证
  和只读投影。计算、远程执行、渲染、报告和邮件由 Skill/Plugin 提供工具实现，
  Kernel 不拥有这些执行过程。
- `extensions/` 提供可选的独立 Pi 工作流扩展。原生 App Server 不注入这些
  扩展；Worker 直接提供受保护的 TSPi 原生工具。
- `components/ts-web/` 是可选的只读浏览器投影。
- TS Phone 是独立 Flutter 客户端，通过 Pi Radius 连接 App Server。

App Server 独占 session directory、对话历史、模型状态、prompt 操作和工作区 Root
锁；本地 TUI 与 TS Phone 连接同一个 owner。原生 Worker 会加载包中对模型可见的
skill 及原生 system prompt；扩展 manifest 不会被默认为当前生效的提示词来源。

## 科学状态模型

工作区的规范文件包括：

```text
workspace.json
research_state.json
phases.json
claims.json
claim_relations.json
research_nodes.json
observations.json
proof_specs.json
validation_results.json
findings.json
acceptances/<acceptance_id>.json
```

Phase 表示研究目标，node 是其中可执行或提供证据的单元。内核在事务提交前验证
全部引用和 schema。

### 最小 Research Kernel

Kernel 的科学主线只有四个角色：`Claim`（科学命题）、`ResearchNode`（一次有明确
问题和交付物的研究事件）、`Observation`（确认后的语义证据）以及统一的
`GateSpec/GateResult`。Hypothesis 通常只是 `status=proposed` 的 Claim；Attempt、
Activity、Run 和原始 artifact 属于执行记录，只有经 Root Agent 核对后才提升为
Observation。

```text
Claim / Hypothesis -> ResearchNode -> Skill/Plugin runs
                                  -> Observation / Finding
                                  -> NodeGate -> Node outcome
                                  -> ClaimGate -> Claim interpretation
```

Kernel 负责 ID、引用、digest、事务和投影；在 Agent 边界上它就是受保护的
`ts_state` / `ts_change` 工具表面，也可管理 workspace identity 和 Node 产物根目录，
但不是另一个 agent runtime。Root Agent 选择问题、方法、分支和停止条件；Skill/Plugin
执行 `ts_calc`、`ts_remote`、`ts_render`、`ts_email` 等工具。工具成功不等于科学
结论成立，也不能直接改变 Claim 状态。

### NodeGate 与 ClaimGate

两者不是两套实体，而是一个 Gate 合约的两个作用域：

```text
GateSpec   = 冻结的收尾/验证标准
GateResult = 对该标准的一次、绑定 digest 和输入 revision 的评估
scope      = node | claim
```

NodeGate 判断一个 bounded Node 是否具备收尾条件，例如交付物已登记、拥有的运行
已结束、阻塞 Finding 已处理。NodeGate `pass` 只允许 Node 进入 terminal outcome，
不表示 Claim 成立。ClaimGate 判断一组证据是否支持、反驳或暂时无法判断 Claim；
它通常由现有 `ProofSpec`、`ValidationResult` 和 Acceptance profile 编译而来。
ClaimGate 结果不会自动更新 Claim 或生成 Acceptance，仍由 Root Agent 通过
`ts_change` 明确解释和提交。

Gate 的产生过程是：Root Agent 选择研究意图和 profile；Plugin 声明可用能力与检查
输入输出；Kernel 展开 profile、校验目标引用、绑定 predicate registry，并在第一次
评估前冻结 `GateSpec`。之后工具只能提供证据，不能静默修改 Gate 标准或 verdict。
`gate_spec.schema.json` 与 `gate_result.schema.json` 已作为独立契约加入。Kernel
同时支持显式 `freeze_gate` / `evaluate_gate` mutation；第一次执行时惰性创建
`gate_specs.json` 与 `gate_results.json`。没有这两个文件的 protocol-6 workspace
仍然有效，并继续得到推导式 Gate projection。

## 独立科学能力与节点管理

`ts_analyze` 通过按需目录派发 22 项版本化独立分析能力，领域实现位于 `analysis/`。
结果绑定 Node、输入 digest、生成文件和候选事实；选定事实通过已有 `ts_change`
入口重算校验后登记。能力不选择下一科学步骤，不接受 Claim。化学网络使用带计量
的超边并允许有环，独立于研究 Node DAG。

`ts_manage` 的暂停/恢复回执位于操作层，不改变 Node 科学状态。共享锁协调暂停
与分析、提交 guard 的边界；在途作业仍可查看、收集和取消。报告和 TS Web 消费
只读投影。详见 [ADR 0002](adr/0002-independent-scientific-capabilities.md) 和
[能力运维文档](SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md)。

Research Map 只读取 Claim、Node、Observation、Gate 结果和依赖历史的投影，展示问题
如何展开、工具运行和证据由哪个 Node 产生、Node 的 outcome、哪个 Gate 阻塞、尚未确定
或已过期；它不把后端运行日志、
Phase 名称或工具退出码直接当成科学状态，也不推断下一步行动。详见
[ADR 0003](adr/0003-minimal-research-kernel-and-gates.md)。

## App Server 生命周期

`TSPi --host` 在 `.pi/app-server-host/` 创建安装级 Host 状态，写入一个稳定 UUID，
获取 Host Root 锁并启动 Pi App Server。`.pi/app-server-host/sessions/` 保存全部会话；
每个会话创建时带有 `workspaces/` 下项目的 cwd，并由 `TSPI_WORKSPACE_ROOT` 限制。
`tspi.workspace-directory` 只暴露包含受支持 `workspace.json` 的直接子工作区。

`TSPi --workspace <name>` 是连接 Host 的 Pi 原生 TUI 客户端，并在创建会话时传递
`TSPI_SESSION_CWD`。TS Phone 通过同一个 service 列出项目、切换项目和会话，无需为
每个项目再次连接或启动 Host。旧的 `--app-server --workspace <name>` 仅作为兼容路径。

## 手机连接

TS Phone 使用 Pi protocol v8 和 `pi-session-relay.client.v1`，通过
`wss://<radius>/v1/session-relays/<server-id>/connect` 一次连接 Host。项目目录和
会话列表由 Host 的 workspace/session services 提供，手机不维护第二套状态机或
Host bridge。

## 其他契约

验证模板位于 `packages/ts-agent-kernel/ts_agent/validation/`；远程计算和产物记录
使用显式 schema。TS Web 只读取工作区文件，不拥有 Pi session。入口、skill、扩展和
测试位置与[英文架构](ARCHITECTURE.md)一致。
