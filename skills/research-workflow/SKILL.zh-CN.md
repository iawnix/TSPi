---
name: research-workflow
description: 在 Pi 原生循环中协调研究问题、领域 Skill、持久 Job、材料和有依据的 Result。
---

# 研究循环

结合原始要求与用户后续的修订、暂停或取消指令，读取相关 Research Memory Node。继续已有问题或创建独立分支，选择方法，检查执行结果，修正判断。[Research Memory Skill](../research-memory/SKILL.zh-CN.md) 提供最小工具示例。一个 Node 可以经历多次尝试，Result 保存有独立价值的不可变观察与判断。

持续工作先用 `task_begin` 登记用户任务，引用实际用户 submission ID 并明确交付条件。`task_read` 在不同 run 间恢复任务。用 `task_update` 记录有依据的进展、等待的明确 Job ID、具体阻塞或完成证据。一个用户任务可以跨多个 Node 和 Job。阶段总结结束的是一次回复；计算等待期间有独立分析可做就继续推进。单个候选耗尽尝试次数时重新评估方法，不擅自结束整个项目。暂停和取消由用户控制。

复杂委托按可独立解释的问题建立 Node 关系，在各自 plan 中记录调查方法，用 `task_update` 的 `set_research` 动作绑定入口与焦点。请求上下文会把这份结构与当前证据一起恢复。单问题可以只有一个 Node，重试和扫描点属于尝试。证据冲突或某路线不再带来信息时，比较剩余方法，选择能减少关键不确定性的工作，记录调整理由并保留失败分支。[规划示例](../research-memory/references/planning.zh-CN.md) 说明如何拆分与重访问题。

领域方法参考适用的已安装 Skill。缺少对应 Skill 或封装时，可使用有依据的方法与任务脚本，明确假设并验证，不能将目录当成能力白名单。Pi 原生 read/write/edit/bash 准备输入、分析和报告；`job_start` 管理科学计算，关联研究时明确传 node_id，不猜“最近一个 Node”。准备和诊断可以没有研究归属。`job_collect` 发布材料与执行回执。

进程成功不等于科学结论成立。按任务检查收敛、几何、频率、连通性和方法局限。research_update 记录解释与计划；research_result 发布可复用结论并引用依据。失败和不确定性都可以如实记录。

重复提交前先读 Job 回执。未知派发结果沿用身份协调，不换身份绕过去重；更换输入的新科学尝试使用新提交身份。Monitor 的 next_run 在所属会话能够接收时恢复事件及相关 Node，不选择科学方案、不要求 checkpoint，也不因 Node open 无限续跑。

Monitor 唤醒后先核对最新用户要求、已有结论与剩余预算；已取消、已完成或达到停止条件的工作不能因事件到达而重启。参数搜索与重试应有有限范围；没有新证据的重复失败需要调整方法或报告阻碍。

交付前读取 email Skill 与配置检查。报告真实结果、缺失工作和限制。保留发送回执；发送后 Memory 更新失败不能重发。Node 状态不构成发送授权。

提出任务完成前，逐项给出交付条件对应的不可变 Result 或材料，并说明剩余 Job。阶段报告和负结果可以构成进展，是否完成取决于用户的交付范围。关闭 Node、追加 note 或改写计划都不证明交付，也不重置无进展计数。科学内容记入 Memory，任务控制使用任务工具，不要求每轮 checkpoint。

- [工具与执行](references/tools.zh-CN.md)
- [精确 Skill 资源路径](references/skills.zh-CN.md)
- [生成的公开合同](references/public_contract.zh-CN.md)
- [English](SKILL.md)
