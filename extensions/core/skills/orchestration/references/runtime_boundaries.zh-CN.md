# Runtime、Research State 与 Monitor 边界

Research State 是 Claim、Node、依赖、策略、checkpoint 和研究 liveness 的唯一权威。
通过公开研究工具读写，不另建工作流状态文件。会话 memory 保存对话；memory/index.json
只是可重建的 State 投影。

Host 绑定工作区与会话身份，管理输入队列和 Pi 回合。State 返回持久状态的工具准入结果，
Harness 只串行化工具调用并记录阶段标记，不另设研究工作流准入图。根据 State 返回的 ready_node_ids、blocked_node_ids 决策，
不从聊天记录或历史别名重新构造生命周期规则。

Job Runtime 管理进程/调度器、日志、查询、取消与收集，State 桥接层关联 Attempt。
Skill 脚本负责科学输入、解析与验证。artifact_derive 只保存派生描述；真实分析必须执行
脚本并登记文件。

Monitor 观察 Job 变化并向所属会话投递去重的 next_run 事件，不收集科学产物、不解释结果、
不改研究节点、不选择计算、不发送邮件。State 决定是否准入；暂缓事件保留至 State 改变，
不重复提示。唤醒后先读 State，再按需调用 job_status/job_collect/job_reconcile。

需要用户输入时，通过 research_change 将对应 Node 设为 blocked 并说明原因，独立节点继续。
存在运行中的 Attempt 时用 waiting_external 引用真实 Attempt ID。只有作用范围内节点均已
blocked/closed 且没有独立可执行或运行中的工作，才能用全局 user_input_required checkpoint。
邮箱地址不是计算的依赖。用户实际回复后，通过恢复 checkpoint 和节点更新继续工作。

公开工具 schema 是接口协议。[public_contract.md](public_contract.zh-CN.md) 从公共契约生成工具名和
disposition；Skill 解释用法，不定义第二套调度器或 capability 注册表。


只有带所属 session 的 continue_required checkpoint 才会由 State 在 liveness 中持久化
continuation 请求。Host 使用已有输入回执消费它，不推导科学流程。相同 revision 不产生
新唤醒，连续接续预算由 State 管理。Monitor 只负责 Job 变化和配置的排队阈值事件。
eligible_node_ids 表示依赖与策略允许执行；ready_node_ids 排除已有运行 Attempt 的范围。
同一合格范围下的新独立 workId 可以提交，但不能据此猜测还有未规划的工作。
