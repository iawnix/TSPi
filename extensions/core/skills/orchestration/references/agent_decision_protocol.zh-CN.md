# 研究决策过程

先使用已提供的 State 快照，只查询缺失或过期的信息。修改前明确问题、不确定性、
负责的 Node 和支持证据。重试沿用 Node；问题或交付物改变时创建后继 Node。
用户要求独立于所选计划保留。

根据现有证据选择下一步。记录科学结论前检查真实输出及其执行记录。运行故障可能
只需要恢复，不必生成科学 Finding；经过核实且有助后续判断的结果或局限才值得登记。

一个 ChangeSet 表达一个连贯决策并说明理由。使用
`research_read mode=operations query=<operation>` 查询当前字段及示例；
[Research State 决策指导](../../research-state/references/decision_contract.zh-CN.md)
解释证据与重新评估。批次被拒绝时没有操作提交，应修复指出的前置条件而不重复外部副作用。

修改后依据返回的 State 继续独立就绪工作、等待正在运行的任务或说明剩余阻塞。
Node 完成、Claim 评估和 requirement 满足回答不同问题。阶段工作完成后，用户要求
仍可能未满足，报告中应保留这个区别。

结束前记录与实际剩余工作一致的 checkpoint。
[生成的公共契约](public_contract.zh-CN.md) 提供当前 disposition。
能继续则继续授权工作；缺失决定阻止后续进展时请求用户输入。以 State 返回的准入
结果判断续跑或等待是否获准。Monitor 唤醒提醒检查执行事实，不负责选择科学方法。

围绕具体不确定性请求咨询审查，提供有关 Claim 和已登记证据，再由研究 Agent 记录
接受、拒绝或限定的解释。审查意见本身不是证据，也不能替代实际执行。
