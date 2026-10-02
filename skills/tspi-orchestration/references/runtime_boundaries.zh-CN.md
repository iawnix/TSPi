# Runtime、Host、Kernel、Memory 与 Monitor 边界

本参考定义 TSPi 公共工具背后的所有权边界。它属于 Agent 可见协议；实现模块名称和进程
名称不会产生额外的 Agent API。

## Agent Runtime

Agent Runtime 负责一次会话/turn 以及进程内的 lifecycle lane。它把请求路由到绑定 workspace
的 Host，并按 `orient`、`advance`、`prepare`、`execute`、`interpret`、`checkpoint` 阶段
准入工具。Monitor 唤醒从 `wake` 开始，只允许先执行一个 orientation read，然后才能继续
正常工作。Runtime 不选择科学方法，不写 Claim 或 Node，也不推断科学结果。

Runtime 的 memory port 始终是 session scope：

```json
{
  "schema_version": "agent_memory_read_1",
  "memory_scope": "session",
  "memory_authority": "agent_core_session",
  "entries": []
}
```

Conversation memory 不是 ResearchMap 状态。在 research workspace 中，Agent Core memory port
收到 `scope=workspace` 会以 `research_memory_authority_required` 失败；workspace 科学状态必须
通过 `research_read`/`research_change` 和类型化 lifecycle 命令跨越 Kernel 边界。

## Host 与 App Server

App Server 是 transport 与组合边界。打开绑定 workspace 的 session 或 tool call 前，必须先
解析已经 admission 的 `workspace_manifest.json`；进程级 Runtime 可以提前构造，但在 manifest
校验完成前不能让 session 使用它。缺失、符号链接、字段不一致、旧协议或只完成一半 admission
的 workspace 必须 fail closed；Host 不得从目录名或旧存储推导 identity。

Host 将 `workspace_id`、`workspace_root` 和 `workspace_mode` 绑定到 request context。Agent
参数可以选择 ResearchMap 对象、capability、Node、Artifact 或已配置环境，但不能替换绑定的
root 或 identity。Host 负责在写入请求中携带 `principal=root_agent` 和
`authority=kernel_write`；Agent 只提供 rationale 和 operations，Kernel 负责校验和提交。

公共 semantic tool 名称是唯一 Agent API：`research_read`、`research_change`、
`research_strategy`、`research_interpretation`、`research_checkpoint`、
`research_continuation`、`compute_environment`、`compute_catalog`、`compute_readiness`、
`compute_run`、
`analysis_run` 以及 `pi_agent_adapter.md` 中列出的 artifact/review 工具。私有
`ts_*` factory 名称和 slash command 都是 transport 细节，不是第二套协议。

## Research Kernel 与 Memory Projection

Research Kernel 拥有规范研究文档和原子 revision。成功的 `research_change` 会把 context、
liveness、`memory/index.json` 和 manifest revision 作为一次 workspace transaction 提交。
Memory index 只是有界 metadata/lifecycle projection，不是 conversation memory，也不能成为第二
个科学权威。Root 必须检查返回 revision 后才能依赖这次变更。

## Monitor

Monitor 负责绑定 Calculation Attempt 的运行态轮询和唤醒投递。它可以读取 scheduler/program
状态、收集已声明输出，并在状态变化时排队 `next_run` 唤醒。唤醒只是运行触发器，不是科学
指令：它不得选择方法、修改 Claim/Node 或启动另一项计算。Root session 重新读取 liveness 和
Attempt，再通过正常公共工具选择 `inspect`、`finalize`、`cancel`、解释或 checkpoint。

## Compute Plane

Capability identity 与 execution environment（`environment_id`、`local` 或 `remote`）相互独立。
计算 descriptor 使用 `capability_id` 与 `capability_version`；analysis catalog 使用
`capability` 与 `version`，`analysis_run` 请求使用 `capability` 加
`capability_version`。这是两个明确的 catalog 协议，不能把字段当作别名混用。实时 catalog
是注册 capability 的唯一来源。两种目标都使用 `compute_run` 的 `launch`、`inspect`、
`finalize` 或 `cancel` 生命周期；`analysis_run` 是没有调度器生命周期的确定性本地分析。
Remote 必须使用 Native `compute_run`，并提供已配置的 `execution.environment`；Host 根据环境配置解析执行平台。
项目不再提供通用 capability invocation；所有 descriptor 均来自 Python Native registry，公开计算请求只能使用生命周期 schema。旧的 `capability_id` 加 `input` 形式会被拒绝。
