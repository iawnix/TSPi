---
name: transition-state-workflow
description: 面向过渡态研究的可审计工作流中文说明。英文 SKILL.md 是 Pi 默认加载的运行策略。
---

# 过渡态研究工作流

[English operating policy](SKILL.md) | [简体中文](SKILL.zh-CN.md)

Root Agent 负责化学推理；确定性代码负责图结构标识、状态、外部效果、
来源记录和验证。

## 不可违反的边界

- 只能通过 `ts_change` 修改规范化科学状态。
- Root Agent 选择问题、假设、方法、分支、停止条件和解释。图边、验证结果
  和标签不能替代 Root Agent 选择下一步行动。
- Claim 关系、Node 依赖和标签只表示已记录的上下文。
- 工具结果在已验证产物支持前只能视为操作记录，不能直接当作 Observation。
- 异常、冲突、限制和未解决问题必须记录为 Finding，不能藏在普通说明文字中。
- 在评估前冻结 ProofSpec。Review、界面、报告和历史接受记录保持只读或建议性。

## 工作循环

1. 已知前后修订时读取 `frontier`，否则读取 `delta`。
2. 写出一个未解决问题、假设、预测和反证条件。
3. 创建或复用 ResearchPhase，启动一个有边界的 ResearchNode，并绑定依赖和
   Claim 范围。活动 Node 应在同一个 Decision 中设置 `set_focus`。
4. 根据化学问题、不确定性、成本和现有产物选择方法。
5. 在所属 Node 下运行有边界的工具；使用 `node_refs` 绑定活动日志。
6. 检查 parser candidate，核对本地原始产物，再通过 `ts_change` 将选定值
   提升为 Observation 或 Finding。
7. 对明确的 Observation 引用冻结并评估 ProofSpec。
8. Attempt 稳定且完成解释后，更新 Claim，并在问题回答后完成 Node。
9. 重新编译上下文，把下一个实质性问题记录为依赖 Node、新 Phase，或明确停止。

一个 Node 对应一个可见的决策问题；重试和重新计算仍然是 Attempt。新问题
应启动新的 Node。回溯时创建依赖旧检查点的新 Node，不删除历史。

## 状态与变更

使用 `ts_state` 进行有边界读取，使用 `ts_change` 提交一个 Root Agent 发起的
原子变更。遇到不熟悉的操作时，先查询：

```text
ts_state mode=change_contract operation=<op>
```

内核负责 ID、`$alias` 解析、校验和原子提交。不要自行生成 ID、路径、回执
或 Decision。

## 验证

使用 `ts_state mode=capabilities capabilityKind=proof` 查询可用 ProofSpec。
编译器会冻结模板、注册表、内容和 Observation 摘要。只有 `pass` 可以满足
ProofSpec；当前通过覆盖率不足或存在适用的阻断 Finding 时不能接受。

## 计算

先用 `mode=locate` 将 Claim、Node、Observation 或 Attempt 映射到逻辑产物。
启动 `ts_calc` 前读取 `mode=artifacts`，并把每个 `artifactId` 绑定到
`inputRole`。Host 负责身份、路径、参数和绑定，Compute 只执行固定操作计划。

没有输入时，先启动 Node；单个 SMILES 使用 `ts_seed`，Gaussian、XYZ 或控制
文本使用 `ts_import`。传递 `artifactId`，不要传递文件路径。

不要轮询没有变化的工作。只有有类型结果证明外部效果没有发生时才重试；提交
或取消结果不明确时不要重放。远程显示 `completed` 后仍需 finalize；存在未解决
或无效 Attempt 时不能完成 Node。

## Review

`ts_review` 从有边界的图和一个逻辑产物批次独立评估一个 Claim，不接收父级
transcript、Skill、原始文件系统、Compute、变更权限或委托权限。Review 是建议，
不能静默修改科学状态。

成功后先调用 `ts_reply`，再通过经过验证的 `ts_change` 应用处置。供应商失败
必须保留为供应商失败，不能伪装成 Review 结论。

## 产物、报告和通知

结构比较、Render、Report 和通知结果在 `ts_change` 记录核验事实前都属于操作
记录。所有接口使用逻辑产物。`ts_notify` 只能发送配置允许的实质事件，收件人
和凭据由 Host 管理。

## 失败边界

- 保留失败 Node 和计算；操作失败本身不推翻 Claim。
- 区分调度器、传输、程序、解析器、科学、Review 供应商、合约、产物和投递失败。
- 远程恢复前检查持久化 guard 和 receipt。
- 经过核验的意外科学结果记录为 Observation 或 Finding，再重新审视问题。

## 参考资料

按当前决策只读取必要的参考文件。术语见
[中英术语表](references/glossary.zh-CN.md)，状态和持久化见
`references/state_model.md`、`references/pathway_model.md`、
`references/workspace_contract.md`，计算和远程边界见
`references/compute_tools.md`、`references/remote_contract.md`，Review 适配见
`references/pi_agent_adapter.md`。
