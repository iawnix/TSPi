## 用户要求与交付

Host 把真实用户消息保存为不可变来源。读取 `mode=sources` 和 `mode=profiles`，
用 `create_requirement` 逐项保存用户交付要求、原文 `source_quote`、已安装的
`acceptance_profile`（`id`、`version`）、明确约束和输入 Artifact ID。
没有新增交付的消息用 `review_source` 附理由标记。来源覆盖仍是 Agent 判断，必须
对照原文独立检查，不能只审自己的计划。`research.material@1` 只适用于材料整理，
不能代替计算要求的科学验收。

用 `bind_requirement` 关联贡献证据的 Node。`revise_requirement` 只能增加范围，
不能删除原始最低检查、约束或输入。`assess_requirement` 消费实际验证 Job 的
result receipt，派生是否满足，不接受人工 pass。`mode=requirements` 显示覆盖、
当前检查和剩余工作。阶段 Node 可先完成；修改 Gate 或 completion_exemption
不能免除 requirement。已完成交付的 requirement_consumption 保留当时版本和
验收；新证据或扩展范围使当前验收需重审，不改写历史交付。新 Attempt 会使旧失败停止
依据过期，必须重新判断。Claim 结论独立，完成约定分析后仍可为 inconclusive。

交付 Node 显式声明 `consumes.requirement_ids`、`consumes.artifact_refs` 或前置依赖。
`dependencies` 的每项为 `{node_id, condition}`；`completed` 要求 closed/completed，
`finished` 允许 closed/completed、inconclusive 或 stopped；旧 `dependency_ids`
仍表示 completed。blocked 不是 finished。已授权的阻塞或失败状态报告可用
`consumes.condition="observed"` 绑定当前范围；成功报告消费满足的要求。
邮件 prepare 绑定当前状态与事件，相关状态变化后必须重新 prepare。

`record_requirement_stop` 需要有来源的取消、匹配范围的执行失败或能力失败证据，
并保留未履行工作；`resume_requirement` 恢复该要求。没准备输入或尚未尝试不等于
能力不可用。缺可信预算记录时不能自行声称预算耗尽。terminal 表示本次运行已收束，
不等于所有科学工作成功；部分完成或取消时应报告未履行要求。旧工作区缺 requirements
仍是 untracked，应恢复原始用户来源，不能自动补成功。

Artifact 类型字段优先使用持久 `artifact_ref`（如 `a1`）；`job_start` 优先传准备
helper 返回的 `prepared_ref`（如 `p1`）。短引用是工作区内不可重新绑定的精确索引，
不是哈希前缀猜测。请求或输入变更后生成新准备记录。陌生写入先查询
`mode=operations query=<操作名>` 获取完整字段。
