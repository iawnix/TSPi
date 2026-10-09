---
name: orchestration
description: 规划和推进 TSPi 研究任务，选择方法、检查证据、继续独立工作，并决定何时停止。
---

# 研究编排

[English](SKILL.md)

使用本 Skill 决定下一步研究工作。research-state 说明如何保存要求与证据，领域
Skill 提供科学方法。本流程适用于计算研究、文献和数据分析等任务。

1. 对照真实用户来源提取交付要求，在选择计划前保存义务。缺少方法或验收模板时，
   要求仍未履行，不能把对应工作从任务中删除。
2. 根据当前 State 快照和已安装的领域 Skill 选择有限的下一步。独立管理的工作
   建立 Node；科学命题使用 Claim；需要解释备选方法、切换条件或预算时记录
   StrategyPlan。简单任务无须占位 Claim 或形式化计划。
3. 保留输入与后续工作的依赖。复用仍有效的结果；Attempt 状态不明时先检查和
   协调，再决定是否提交。一个分支不可用，不妨碍其它已授权的独立分支。
4. 科学计算通过显式配置执行环境的 Job 完成，收集并检查证据。准备和验证方法
   来自所选领域 Skill；调度器或进程探测通过不能证明科学方法可用。
5. 用当前证据评估用户交付和已附加的 Gate。仅在观察或问题值得复用时记录
   Finding。计算执行成功不会自动支持科学 Claim。
6. 使用对应已安装 Skill 完成授权交付。收件人或交付依赖缺失时继续独立研究。
   State 登记失败后保留既有外部效果回执，恢复登记，不重复执行外部效果。
7. 结束前对当前范围 checkpoint。有可执行工作时继续；仅剩外部执行时选择
   waiting_external。只有缺失决策阻止所有剩余授权工作时才请求用户输入。
   部分停止时明确报告未履行要求。

按工具错误指出的前置条件修复。原子 ChangeSet 出错表示整个批次未提交；保留
已完成工作与回执。可选诊断失败不必阻止独立工作。

## 参考

- [决策流程](references/agent_decision_protocol.zh-CN.md)
- [Job](references/compute_tools.zh-CN.md) 与 [Artifact](references/artifact_tools.zh-CN.md)
- [运行失败恢复](references/program_runtime_failures.zh-CN.md)
- [Root 工具](references/pi_agent_adapter.zh-CN.md) 与 [公开契约](references/public_contract.zh-CN.md)
- [运行时边界](references/runtime_boundaries.zh-CN.md)
- [安装资源](references/package_sources.zh-CN.md)
