---
name: orchestration
description: 在 Skill、ResearchNode、分支、重试、评审与停止决策之间规划并推进 TSPi 研究任务。
---

# TSPi 任务编排

[English version](SKILL.md)

当 Root 需要决定下一步研究工作时使用本 Skill。ResearchMap 的结构、读取和写入由
`research-state` 负责；本 Skill 不重复定义该模型。

## 工作流

1. 先使用当前回合已有的 State 快照；规划需要的信息缺失或过期时，才按最小范围调用 `research_read`。
2. 说明不确定性、相关 Claim，以及一个边界明确的交付物。
3. 先通过 `research_change` 创建或确认 Claim 和 Node，再用 `research_strategy` 建立覆盖 focus 的计划。未知 Claim 错误应先创建对象，再重试策略；没有策略时不要跳到证据写入或计算。
   从系统提示列出的真实路径读取科学 Skill。用户已指定方法时仍使用 method-selection 的执行准备：读取安装 job.toml，绑定配置的解释器、软件和环境。job_probe 只验证通用平台，方法可用性由 Skill 检查。
   对方法比较建立 `方法 × environment × {opt, sp}` 矩阵，保存方法、环境、输入和依赖。单点使用相同方法与环境的优化坐标；只阻塞失败单元，不停止独立任务。
4. 在所属 Node 下启动或检查任务，并将 Attempt 与 Artifact 留在该 Node 下。
5. 检查证据后记录有用的 FactFinding 或 IssueFinding；已登记文献和导入数据也可作为来源，计划不能充当 confirmed 事实。Finding 本身不会改变 Node 或 Claim 的状态。
6. 对照替代解释与停止条件决定：继续同一 Node、为新问题建立依赖 Node、为竞争方法或
   假设建立分支，或显式停止。
7. 只有交付物已处理且所附每个 NodeGate 的最新评估均为 `pass` 时，才能把 Node 以
   `completed` 关闭；科学 Claim 状态通过带理由和已登记证据的 `assess_claim` 更新。

## Research Turn 收尾

研究回合结束前先使用最新 State 快照，仅当需要的信息缺失或过期时读取 `context` 或 `liveness`，并使用
`research_checkpoint` 结束生命周期。需要时先记录 strategy 和 Attempt interpretation，再选择一个
明确 disposition：`continue_required`、`waiting_external`、`deferred`、`blocked`、`terminal` 或
`user_input_required`。`research_checkpoint` 是规范的 turn checkpoint。
Attempt 或 lifecycle action 完成本身都不是研究结论。若 liveness 返回
`decision_needed` 且没有明确 disposition，才需要补充策略或 checkpoint。成功记录 `user_input_required` 后应结束当前 turn，即使旧投影同时返回 `decision_needed`；不要重复 checkpoint 或反复尝试被拒的写入。如果 liveness 同时返回
`execution_ready=true`，说明 focus 已有 active StrategyPlan，可以先执行该计划对应的
prepare/execute，但结束 turn 前仍必须写入 checkpoint。`continue_required` 是合法的下一轮计划，
Harness 不应在同一 turn 强行执行它。Harness 不得替 Agent 发明方法，Monitor 的 `next_run` 也不是
新的科学指令。

本地与远端科学计算都通过 `job_start/job_status/job_collect` 执行。提交后保存 Job/Attempt 身份，结果不确定时先 reconcile 再考虑重试。只剩外部工作时记录 `waiting_external` 并结束，由 Monitor 在有意义的变化后唤醒；其他已规划且独立的 Node 可以继续。不要用 sleep 循环轮询。请求准备、已有结果的报告整理和邮件 CLI 全部通过原生 bash 执行；这些操作产生文件、回执与 Artifact，不创建计算 Attempt。

用 `artifact_register` 或 `artifact_create` 保存真实产物，以 `artifact_link` 关联证据。`artifact_derive` 只记录派生描述；实际分析通过 Skill Job 执行，再登记结果。运行成功不等于科学结论成立，需解释证据后再更新结论。

用户要求邮件时，先读取列出的 email Skill，通过 bash 使用安装配置运行无发送副作用的 `check`，再判断是否缺地址。收件人问题只阻塞交付，计算和交付存在不同依赖时应分设 Node。只有没有独立的已授权工作可继续时，才把整个活动范围设为 `user_input_required`。方法可用性尚未验证应由 Agent 调查，不能默认要求用户提供证明。

## 参考资料

- 分支、恢复和停止决策见
  [agent_decision_protocol.zh-CN.md](references/agent_decision_protocol.zh-CN.md)。
- 公共执行和 Artifact 调用见 [compute_tools.zh-CN.md](references/compute_tools.zh-CN.md) 与
  [artifact_tools.zh-CN.md](references/artifact_tools.zh-CN.md)。
- Attempt 失败或效果未知时见
  [program_runtime_failures.zh-CN.md](references/program_runtime_failures.zh-CN.md)。
- Root 工具和 slash command 见
  [pi_agent_adapter.zh-CN.md](references/pi_agent_adapter.zh-CN.md)。
- Agent Runtime、Host/App Server、memory、Research State、Monitor 与 compute 所有权边界见
  [runtime_boundaries.zh-CN.md](references/runtime_boundaries.zh-CN.md)。
- 仅在检查已安装包源码时读取
  [package_sources.zh-CN.md](references/package_sources.zh-CN.md)。

## 运行观测与恢复

普通探测保留在工具记录中，不必写为 FactFinding；探测后继续准备输入并执行。需要支持
决策或跨回合引用时，才登记原始观测 Artifact，并使用返回的 artifact_id 作为 source_refs。
工具名与自造 ID 不是证据。可选 Finding 失败不得阻止独立准备；可选诊断与必需节点更新
分开提交。策略或输入证据等真实前置条件失败仍需修复。

按 [运行边界](references/runtime_boundaries.zh-CN.md) 处理局部用户等待。可独立执行的方法/
环境组合优先使用独立 Node，邮件使用依赖结果的交付 Node。按系统列出的精确路径读取 email
Skill，路径读取失败不代表邮件能力或收件人不存在。

- [Public contract / 公开契约](references/public_contract.zh-CN.md): generated tool names and dispositions.

`continue_required` 会由 State 持久化接续请求，Host 在当前轮结束后通过 Pi 提交。检查返回的 continuation 决定：同一研究 revision 只接续一次，连续推进最多自动接续八次。被拒绝时说明原因，不承诺自动续跑。Node 是研究范围；同 Node 的独立任务必须保留 helper 生成的不同 work_id，已提交工作先 collect/reconcile。

完成结果核验、报告整理与已授权交付后再写最终 checkpoint。计算失败时先继续独立的已授权工作，再判断是否全局 blocked。“完成后发结果”不自动授权失败通知。已 blocked 的范围须先通过显式恢复 checkpoint 再更新 Node 或调用 bash，不能直接编辑状态文件。

## 完成条件与恢复

每个执行或交付 Node 都应在首次产生外部效果前声明 Gate 或有理由的 completion_exemption。独立方法/环境分别建立 Node，报告和邮件建立依赖节点。前置节点证据通过后关闭；check/prepare 可提前执行，实际发送要求交付节点已具备执行条件。Job 退出或 SMTP 回执本身不关闭 Node。

research_change 失败时检查 operation_index、operation_type、target_id：整批已回滚，但前面操作可能正确。用 research_read mode=operations query=evaluate_gate 查询嵌套合同和示例，只修复指出的目标，不猜字段或重复原请求。邮件须登记并检查已有回执，评估交付 Gate、关闭节点，再写 checkpoint。状态登记失败后复用 sent 回执，不重新发送。
