---
name: research-workflow
description: 在 Pi 原生循环中协调研究问题、领域 Skill、持久 Job、材料和有依据的 Result。
---

# 研究循环

读取原始要求与相关 Research Memory Node。继续已有问题或创建独立分支，选择方法，检查执行结果，修正判断。[Research Memory Skill](../research-memory/SKILL.zh-CN.md) 提供最小工具示例。一个 Node 可以经历多次尝试，Result 保存有独立价值的不可变观察与判断。

领域方法使用已安装 Skill。Pi 原生 read/write/edit/bash 准备输入、分析和报告；`job_start` 管理科学计算，关联研究时明确传 node_id，不猜“最近一个 Node”。准备和诊断可以没有研究归属。`job_collect` 发布材料与执行回执。

进程成功不等于科学结论成立。按任务检查收敛、几何、频率、连通性和方法局限。research_update 记录解释与计划；research_result 发布可复用结论并引用依据。失败和不确定性都可以如实记录。

重复提交前先读 Job 回执。未知派发结果沿用身份协调，不换身份绕过去重；更换输入的新科学尝试使用新提交身份。Monitor 的 next_run 在所属会话能够接收时恢复事件及相关 Node，不选择科学方案、不要求 checkpoint，也不因 Node open 无限续跑。

交付前读取 email Skill 与配置检查。报告真实结果、缺失工作和限制。保留发送回执；发送后 Memory 更新失败不能重发。Node 状态不构成发送授权。

- [工具与执行](references/tools.zh-CN.md)
- [精确 Skill 资源路径](references/skills.zh-CN.md)
- [生成的公开合同](references/public_contract.zh-CN.md)
- [English](SKILL.md)
