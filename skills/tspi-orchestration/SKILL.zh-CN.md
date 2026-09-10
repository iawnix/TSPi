---
name: tspi-orchestration
description: TSPi 可审计研究任务、工作区状态、Decision、证据、验证、子代理和运行恢复的编排与管理合同。
---

# TSPi 编排与管理

[English version](SKILL.md)

这是 TSPi 的任务管理与合同 Skill。它定义研究问题如何变成有边界的
ResearchNode，操作如何记录，以及已核验的证据如何进入规范化状态。它不
选择具体化学方法。当前问题需要方法知识或交付能力时，再加载
`tspi-transition-state-search`、`tspi-xtb`、`tspi-gaussian`、`tspi-qbics`、
`tspi-connectivity`、`tspi-render`、`tspi-report` 或 `tspi-email`。

## 权限与状态

- Root Agent 选择问题、假设、方法、分支、停止条件和解释。
- Research Kernel 负责 ID、Schema、引用、事务、路径、来源和验证。
- 只有 `ts_change` 可以修改规范化科学状态。
- Claim 关系、Node 依赖和标签只作为已记录的上下文，不选择下一个任务。
- 工具结果在已验证产物支持前只属于操作记录。
- Review、界面、报告和历史接受记录只读或具有建议性；评估前冻结 ProofSpec。

## 任务循环

1. 读取 `frontier`；已知前后修订时读取 `delta`。
2. 写明一个未解决问题、假设、预测和反证条件。
3. 创建或复用 ResearchPhase，启动一个有边界的 ResearchNode，明确依赖和
   Claim 范围，并有意识地设置 focus。
4. 加载相应领域 Skill，根据问题、不确定性、成本和现有产物选择方法。
5. 在所属 Node 下运行有边界的工具，使用逻辑 artifact ID，并保持 Node
   开放直到解释完成。
6. 检查 parser candidate 和原始产物，通过 `ts_change` 将已核验值提升为
   Observation 或 Finding。
7. 对明确 Observation 引用冻结并评估 ProofSpec。
8. 在问题回答后更新 Claim 并完成 Node。
9. 重新编译上下文，把下一个实质问题记录为依赖 Node、新 Phase，或明确停止。

一个 Node 对应一个可见问题和交付物。保持同一问题的重试仍是 Attempt；问题、
交付物或假设范围改变时启动依赖 Node。回溯时创建依赖旧检查点的新 Node，并
保留全部历史。Decision 的边界见 `references/agent_decision_protocol.md`。

## 变更与验证

使用 `ts_state` 进行有边界读取，使用 `ts_change` 提交一次 Root Agent 发起的
原子变更。遇到不熟悉的操作时先查询
`ts_state mode=change_contract operation=<op>`，严格遵循返回字段。不要自行
生成 ID、路径、回执或 Decision。

使用 `ts_state mode=capabilities capabilityKind=proof` 查询版本化 ProofSpec。
编译器绑定模板、谓词注册表、内容和 Observation 摘要。只有 `pass` 满足
ProofSpec；接受还要求当前覆盖完整且没有适用的开放阻断 Finding。

## 操作边界

启动 `ts_calc` 前使用 `mode=locate` 和 `mode=artifacts`，用 `artifactId` 和
`inputRole` 绑定每个输入。Host 负责身份、路径、参数和外部效果。远程
`completed` 仍需收集和 finalize；提交、取消或通知结果不明确时不要重放。

`ts_review` 只接收一个有边界的 Claim dossier 和产物批次，不接收父级 transcript、
原始文件系统、Compute、变更权限或委托权限。成功后先调用 `ts_reply`，再通过
`ts_change` 应用建议。区分调度器、传输、程序、解析器、科学、合同、产物、
Review 供应商和投递失败，保留失败 Node 与 Attempt。

## 合同参考路由

按当前操作只读取所需合同：

| 需要 | 参考文件 |
| --- | --- |
| 公开术语 | `references/glossary.md`、`references/glossary.zh-CN.md` |
| 状态、身份、DAG 和持久化 | `references/state_model.md`、`references/pathway_model.md`、`references/workspace_contract.md` |
| Decision 字段和提交纪律 | `references/decision_contract.md`、`references/agent_decision_protocol.md` |
| 计算和后端执行合同 | `references/compute_tools.md`、`references/backend_contract.md` |
| 远程、运行时和程序失败 | `references/remote_contract.md`、`references/runtime_environment.md`、`references/program_runtime_failures.md` |
| Review 隔离与 Pi 上下文 | `references/pi_agent_adapter.md` |
| 结构产物操作 | `references/artifact_tools.md` |
| 渲染 | `tspi-render/references/render_contract.md` |
| 报告 | `tspi-report/references/report_template.md` |
| 通知投递 | `tspi-email/references/email_delivery.md` |
| 源码与安装源 | `references/package_sources.md` |

方法和交付参考资料放在各自 Skill 中：搜索方法、xTB/CREST、Gaussian、
QBICS/DMECP、端点和结构证据，以及渲染、报告和邮件通知分别使用对应的
`tspi-*` Skill。
