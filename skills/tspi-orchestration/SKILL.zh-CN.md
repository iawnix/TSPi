---
name: tspi-orchestration
description: 在 Skill、ResearchNode、分支、重试、评审与停止决策之间规划并推进 TSPi 研究任务。
---

# TSPi 任务编排

[English version](SKILL.md)

当 Root 需要决定下一步研究工作时使用本 Skill。ResearchMap 的结构、读取和写入由
`tspi-research-kernel` 负责；本 Skill 不重复定义该模型。

## 工作流

1. 规划前读取当前 ResearchMap 和聚焦对象。
2. 说明不确定性、相关 Claim，以及一个边界明确的交付物。
3. 复用或创建 ResearchNode。只有在分组有助于导航时才添加 Phase。根据问题选择科学
   Skill、Backend 与计算环境。
4. 在所属 Node 下启动或检查任务，并将 Attempt 与 Artifact 留在该 Node 下。
5. 检查原始输出后，通过 Kernel 记录粒度明确的 FactFinding 与 IssueFinding。Finding
   本身不会改变 Node 或 Claim 的状态。
6. 对照替代解释与停止条件决定：继续同一 Node、为新问题建立依赖 Node、为竞争方法或
   假设建立分支，或显式停止。
7. 只有交付物已处理且所附每个 NodeGate 的最新评估均为 `pass` 时，才能把 Node 以
   `completed` 关闭；Claim 状态另行更新。

## Research Turn 收尾

每轮结束前，读取 `research.read` 的 `mode=context` 或 `mode=liveness`，并让当前活动 scope
处于明确的生命周期状态：用 `research.continuation operation=set_required` 登记具体下一动作；存在
已提交 Attempt 时保持外部等待；带原因记录 `deferred` 或 `blocked`；或在证据和 Gate 均满足
后关闭相关 map scope。Attempt 已完成或 Continuation 已完成本身都不是研究结论。若 liveness
返回 `decision_needed`，必须继续当前 turn 并登记 disposition。`required` 表示已经登记了
下一轮的具体动作，是合法的 checkpoint，Harness 不应在同一 turn 强行执行它。Harness
不得替 Agent 发明方法，Monitor 的 `next_run` 也不是新的科学指令。

Review 只提供有边界的反方审查，不拥有规范状态。本地与远端环境使用同一组
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
- 仅在检查已安装包源码时读取
  [package_sources.zh-CN.md](references/package_sources.zh-CN.md)。
