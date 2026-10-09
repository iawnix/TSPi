---
name: research-state
description: 保存用户要求，检查研究进度与证据，通过公开工具更新 TSPi 的规范研究状态。
---

# Research State

[English](SKILL.md)

使用本 Skill 跨轮保存研究义务、证据与决策。优先读取已有 State 快照；缺少细节
或信息过期时，用最小范围的 research_read 查询。陌生 research_change 操作的
字段规范和示例以 operations 模式返回的契约为准。

- Requirement 保存用户交付及最低验收要求。即使方法或模板不可用，也要根据
  真实用户来源登记。profile 是可选检查模板；任务可组合运行事实、注册验证器
  结果和明确的 Agent 判断。详见[要求与交付](references/requirements.zh-CN.md)。
- Node 表示工作范围和依赖，可先于整个任务完成。Claim 表示科学命题，通过
  assess_claim 保存基于证据的状态；Phase 只帮助导航。简单任务不强制 Claim
  或 Phase。
- Artifact 标识真实材料，包括文献与导入数据；Attempt 标识执行。Finding
  和解释引用注册证据。artifact_derive 只描述拟做分析，实际执行后才能使用结果。
- Gate 对特定 Node 或 Claim 应用检查条件。有明确判断需要时再附加；已附加的
  Gate 必须当前通过，才能完成对应 Node 或支持 Claim。普通 Node 不强制 Gate
  或豁免，关闭 Node 也不会自动履行 Requirement。
- StrategyPlan 保存有意义的方法选择和备选方案，解释记录说明已检查的 Attempt
  结果。两者可只关联 Node，不必编造 Claim。日常工具观察可保留在工具历史中。

通过公开工具写入，不编辑规范状态文件。旧状态下写入可能不安全时使用
expected_revision。引用真实已有对象。批次错误给出 operation_index 与 target_id，
修复对应对象并保留回执，不重复外部效果。Node/Claim 状态需明确更新；Finding、
Job 退出或 Gate 评估不会代为完成状态转换。

结束前用 research_checkpoint 声明当前范围的 disposition。blocked 或
user_input_required 范围开始新工作前需恢复 checkpoint；成功的
user_input_required 表示本轮结束。有独立可执行 Node 或运行 Attempt 时不能
全局等待用户。continue_required 为所属会话保存有限续行；承诺下一轮前检查
返回的准入决定。

## 参考

- [要求与交付](references/requirements.zh-CN.md)
- [状态模型](references/state_model.zh-CN.md)与[术语](references/glossary.zh-CN.md)
- [决策契约](references/decision_contract.zh-CN.md)
- [工作区职责](references/workspace_contract.zh-CN.md)
