---
name: tspi-orchestration
description: 编排 TSPi 研究任务，管理工作区状态、Decision、证据、验证、子代理和运行恢复。
---

# TSPi 编排与管理

[English version](SKILL.md)

使用本 Skill 组织研究问题、记录计算并验证 Claim。将每个问题表示为
ResearchNode，并把结果关联到工作区的科学记录。当前问题需要方法知识或
交付能力时，加载
`tspi-transition-state-search`、`tspi-xtb`、`tspi-gaussian`、
`tspi-connectivity`、`tspi-render`、`tspi-report` 或 `tspi-email`。

## 研究记录

- Root Agent 选择问题、假设、方法、分支、停止条件和解释。
- Research Kernel 负责 ID、Schema、引用、事务、路径、来源和验证。
- 通过 `ts_change` 提交科学状态变更。
- 通过 Claim 关系、Node 依赖和标签理解已有工作，根据问题和现有证据选择下一任务。
- 对照产物核验工具输出，再记录 Observation 或 Finding。
- 解释 Claim 时结合 Review 建议和当前验证结果；评估前冻结 ProofSpec。

## 任务循环

1. 读取 `frontier`；已知上次的科学与运行修订时读取 `delta`。
2. 写明一个未解决问题、假设、预测和反证条件。
3. 创建或复用 ResearchPhase，启动一个对应具体决策的 ResearchNode，明确依赖和
   Claim 范围，并有意识地设置 focus。
4. 加载相应领域 Skill，根据问题、不确定性、成本和现有产物选择方法。
5. 在所属 Node 下运行具体工具操作，使用逻辑 artifact ID，并保持 Node
   开放直到解释完成。
6. 检查 parser candidate 和原始产物，通过 `ts_change` 将已核验值提升为
   Observation 或 Finding。
7. 对明确 Observation 引用冻结并评估 ProofSpec。
8. 更新 Claim 状态；对已获支持且准备接受的 Claim 运行 `accept_claim`。
   问题和相关操作处理完后完成 Node。
9. 重新编译上下文，把下一个实质问题记录为依赖 Node、新 Phase，或明确停止。

一个 Node 对应一个可见问题和交付物。保持同一问题的重试仍是 Attempt；问题、
交付物或假设范围改变时启动依赖 Node。回溯时创建依赖旧检查点的新 Node，并
保留全部历史。Decision 的边界见 [agent_decision_protocol.md](references/agent_decision_protocol.md)。

## 变更与验证

使用 `ts_state` 按范围读取，使用 `ts_change` 提交一次 Root Agent 发起的
原子变更。遇到不熟悉的操作时先查询
`ts_state mode=change_contract operation=<op>`，按返回字段填写请求。
使用工具返回的 ID、路径和回执；Decision ID 由 Kernel 在提交变更时分配。

使用 `ts_state mode=capabilities capabilityKind=proof` 查询版本化 ProofSpec。
编译器绑定模板、谓词注册表、内容和 Observation 摘要。只有 `pass` 满足
ProofSpec；接受还要求当前覆盖完整且没有适用的开放阻断 Finding。

## 计算与 Review

启动 `ts_calc` 前使用 `mode=locate` 和 `mode=artifacts`，用 `artifactId` 和
`inputRole` 绑定每个输入。Host 负责身份、路径、参数和外部效果。远程
`completed` 仍需收集和 finalize。提交、取消或通知结果未知时，先检查回执和
外部状态，再决定后续处理。

`ts_review` 在独立会话中评估一份 Claim 材料和选定产物批次。先调用 `ts_reply`，再通过
`ts_change` 应用建议。区分调度器、传输、程序、解析器、科学、合同、产物、
Review 供应商和投递失败，保留失败 Node 与 Attempt。

## 合同参考路由

按当前操作只读取所需合同：

| 需要 | 参考文件 |
| --- | --- |
| 公开术语 | [glossary.md](references/glossary.md)、[glossary.zh-CN.md](references/glossary.zh-CN.md) |
| 状态、身份、DAG 和持久化 | [state_model.md](references/state_model.md)、[pathway_model.md](references/pathway_model.md)、[workspace_contract.md](references/workspace_contract.md) |
| Decision 字段和提交纪律 | [decision_contract.md](references/decision_contract.md)、[agent_decision_protocol.md](references/agent_decision_protocol.md) |
| 计算和后端执行合同 | [compute_tools.md](references/compute_tools.md)、[backend_contract.md](references/backend_contract.md) |
| 远程、运行时和程序失败 | [remote_contract.md](references/remote_contract.md)、[runtime_environment.md](references/runtime_environment.md)、[program_runtime_failures.md](references/program_runtime_failures.md) |
| Review 隔离与 Pi 上下文 | [pi_agent_adapter.md](references/pi_agent_adapter.md) |
| 结构产物操作 | [artifact_tools.md](references/artifact_tools.md) |
| 渲染 | [渲染接口](../tspi-render/references/render_contract.md) |
| 报告 | [报告模板](../tspi-report/references/report_template.md) |
| 通知投递 | [邮件投递](../tspi-email/references/email_delivery.md) |
| 源码与安装源 | [package_sources.md](references/package_sources.md) |

方法和交付参考资料放在各自 Skill 中：搜索方法、xTB/CREST、Gaussian、
端点和结构证据，以及渲染、报告和邮件通知分别使用对应的
`tspi-*` Skill。
