# 架构

TSPi 在 Pi 之上提供计算化学 skill 和工作流扩展。每个工作区运行一个原生 Pi
App Server，不再有共享的 TS Phone Host。

## 组件职责

- `apps/app-server/` 启动 Pi 原生 App Server 和 session worker。
- `packages/ts-agent-kernel/ts_agent/` 管理科学契约、工作区状态、验证、远程计算、
  渲染和报告。
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

## 独立科学能力与节点管理

`ts_analyze` 通过按需目录派发 22 项版本化独立分析能力，领域实现位于 `analysis/`。
结果绑定 Node、输入 digest、生成文件和候选事实；选定事实通过已有 `ts_change`
入口重算校验后登记。能力不选择下一科学步骤，不接受 Claim。化学网络使用带计量
的超边并允许有环，独立于研究 Node DAG。

`ts_manage` 的暂停/恢复回执位于操作层，不改变 Node 科学状态。共享锁协调暂停
与分析、提交 guard 的边界；在途作业仍可查看、收集和取消。报告和 TS Web 消费
只读投影。详见 [ADR 0002](adr/0002-independent-scientific-capabilities.md) 和
[能力运维文档](SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md)。

## App Server 生命周期

`TSPi --app-server --workspace <name>` 按需创建工作区，在
`.pi/app-server/server-id` 写入稳定 UUID，获取 Root 锁并启动 Pi App Server。
`.pi/app-server/sessions/` 保存会话，私有 Unix socket 位于用户 runtime 目录。

`TSPi --workspace <name>` 是连接该 socket 的 Pi 原生 TUI 客户端。同一工作区若已有
App Server，第二次启动会因 Root 锁失败，不会产生第二份历史。

## 手机连接

TS Phone 使用 Pi protocol v8 和 `pi-session-relay.client.v1`，通过
`wss://<radius>/v1/session-relays/<server-id>/connect` 连接 App Server。手机不维护
workspace catalog、事件队列或 Host bridge。

## 其他契约

验证模板位于 `packages/ts-agent-kernel/ts_agent/validation/`；远程计算和产物记录
使用显式 schema。TS Web 只读取工作区文件，不拥有 Pi session。入口、skill、扩展和
测试位置与[英文架构](ARCHITECTURE.md)一致。
