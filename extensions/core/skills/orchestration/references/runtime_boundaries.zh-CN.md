# Runtime、Research State 与 Monitor 边界

Research State 管理用户要求、研究决策及 liveness。根据当前投影判断哪些工作就绪或
阻塞。通过公共工具修改；对话历史和 memory 投影不能替代 State。

Host 管理身份、客户端连接和路由。Pi Harness/Worker 管理输入准入、队列、中断及
持久 submission。终端、手机和经过认证的内部事件使用同一准入路径。
State 提供研究准入判断，Skill 解释在这些约束内如何作研究选择。

Job Runtime 管理进程、调度器、日志、取消与文件收集，State 桥接层关联 Job 与 Attempt。
领域扩展声明科学执行入口和验证器，其 Skill 说明方法选择与结果解释。
artifact_derive 只描述分析，不运行分析；通过 Job 执行后才能将输出用作证据。

Monitor 观察 Job 变化，将事件放入所属会话的 outbox。Worker 按当前 State 准入并记录
Pi submission。事件待投递不代表模型已经消费。Monitor 不收集输出、不解释科学、不选
方法、不发送邮件。唤醒后检查 State，按需使用 job_status、job_collect 或 job_reconcile。

State 管理显式 continuation 请求及预算，Worker 使用同一持久输入路径准入。
Host 和 Skill 不重建另一套研究调度器。工具与 checkpoint disposition 见
[生成的公共契约](public_contract.zh-CN.md)。

将阻塞限定到受影响的工作。交付细节缺失不必阻止独立计算。继续就绪工作，等待真实
运行中的 Attempt，确实需要用户决定才能推进时再请求输入。用户回复后先记录恢复，
更新受影响的 Node，再重启相应工作。
