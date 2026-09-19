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

Review 只提供有边界的反方审查，不拥有规范状态。本地与远端环境使用同一组
`launch`、`inspect`、`finalize`、`cancel` 生命周期；运行成功不等于科学结论成立。

## 参考资料

- 分支、恢复和停止决策见 [agent_decision_protocol.md](references/agent_decision_protocol.md)。
- 公共执行和 Artifact 调用见 [compute_tools.md](references/compute_tools.md) 与
  [artifact_tools.md](references/artifact_tools.md)。
- Attempt 失败或效果未知时见
  [program_runtime_failures.md](references/program_runtime_failures.md)。
- Root 工具和 slash command 见 [pi_agent_adapter.md](references/pi_agent_adapter.md)。
- 仅在检查已安装包源码时读取 [package_sources.md](references/package_sources.md)。
