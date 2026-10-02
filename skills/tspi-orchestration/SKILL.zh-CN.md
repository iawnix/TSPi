---
name: tspi-orchestration
description: 在 Skill、ResearchNode、分支、重试、评审与停止决策之间规划并推进 TSPi 研究任务。
---

# TSPi 任务编排

[English version](SKILL.md)

当 Root 需要决定下一步研究工作时使用本 Skill。ResearchMap 的结构、读取和写入由
`tspi-research-state` 负责；本 Skill 不重复定义该模型。

## 工作流

1. 规划前读取当前 ResearchMap 和聚焦对象。
2. 说明不确定性、相关 Claim，以及一个边界明确的交付物。
3. 复用或创建 ResearchNode。只有在分组有助于导航时才添加 Phase。根据问题选择科学
   Skill、Backend 与计算环境。对命名的执行目标，必须使用精确的 capability、environment
   和 execution kind 查询 readiness；默认 readiness 不验证其他环境。
4. 在所属 Node 下启动或检查任务，并将 Attempt 与 Artifact 留在该 Node 下。
5. 检查原始输出后，通过 Kernel 记录粒度明确的 FactFinding 与 IssueFinding。Finding
   本身不会改变 Node 或 Claim 的状态。
6. 对照替代解释与停止条件决定：继续同一 Node、为新问题建立依赖 Node、为竞争方法或
   假设建立分支，或显式停止。
7. 只有交付物已处理且所附每个 NodeGate 的最新评估均为 `pass` 时，才能把 Node 以
   `completed` 关闭；Claim 状态另行更新。

## Research Turn 收尾

每轮结束前，读取 `research_read` 的 `mode=context` 或 `mode=liveness`，并使用
`research_checkpoint` 结束生命周期。需要时先记录 strategy 和 Attempt interpretation，再选择一个
明确 disposition：`continue_required`、`waiting_external`、`deferred`、`blocked`、`terminal` 或
`user_input_required`。`research_checkpoint` 是规范的 turn checkpoint。
Attempt 或 lifecycle action 完成本身都不是研究结论。若 liveness 返回
`decision_needed`，必须继续当前 turn 并记录 checkpoint。如果 liveness 同时返回
`execution_ready=true`，说明 focus 已有 active StrategyPlan，可以先执行该计划对应的
prepare/execute，但结束 turn 前仍必须写入 checkpoint。`continue_required` 是合法的下一轮计划，
Harness 不应在同一 turn 强行执行它。Harness 不得替 Agent 发明方法，Monitor 的 `next_run` 也不是
新的科学指令。

Review 只提供有边界的反方审查，不拥有规范状态。`analysis_run` 仅用于从分析目录中发现的
精确 capability/version；它是已注册的确定性本地分析，没有计算生命周期。对需要审计的
local/remote 计算，`compute_run` 是计算生命周期入口，负责 Attempt、Artifact、Monitor 以及
launch 生命周期。每个计算都记录在 ResearchNode 的 Attempt 下。Review 只能提供
建议，不能写入 ResearchMap、改变 Claim/Node 状态、选择方法、启动或取消 Compute。
`review_respond` 后由 Root 使用普通 `research_change` 记录接受、拒绝或附带条件的解释。本地与远端环境使用同一组
`launch`、`inspect`、`finalize`、`cancel` 生命周期。`launch` 返回提交结果（包括结果不确定）后应结束当前
turn，让持久化 Monitor 投递 `next_run`；不要用 `bash sleep`、`wait` 或手动轮询等待
调度器任务。收到 Monitor 唤醒或用户稍后明确请求后，重新读取状态并先执行
`inspect`，再决定是否收集或修改 ResearchMap。运行成功不等于科学结论成立。

## 参考资料

- 分支、恢复和停止决策见
  [agent_decision_protocol.zh-CN.md](references/agent_decision_protocol.zh-CN.md)。
- 公共执行和 Artifact 调用见 [compute_tools.zh-CN.md](references/compute_tools.zh-CN.md) 与
  [artifact_tools.zh-CN.md](references/artifact_tools.zh-CN.md)。
- Attempt 失败或效果未知时见
  [program_runtime_failures.zh-CN.md](references/program_runtime_failures.zh-CN.md)。
- Root 工具和 slash command 见
  [pi_agent_adapter.zh-CN.md](references/pi_agent_adapter.zh-CN.md)。
- Agent Runtime、Host/App Server、memory、Kernel、Monitor 与 compute 所有权边界见
  [runtime_boundaries.zh-CN.md](references/runtime_boundaries.zh-CN.md)。
- 仅在检查已安装包源码时读取
  [package_sources.zh-CN.md](references/package_sources.zh-CN.md)。
