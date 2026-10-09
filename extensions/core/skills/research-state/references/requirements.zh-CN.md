## 用户要求与交付

Worker 准入把真实用户消息保存为不可变来源。读取 `mode=sources` 和 `mode=profiles`，
用 `create_requirement` 逐项保存用户交付要求、原文 `source_quote`、明确约束和输入
Artifact ID。`acceptance_profile`（`id`、`version`）是可选模板。没有模板或执行
能力也必须登记要求；尚未定义检查或模板不可用时保持未履行。
没有新增交付的消息用 `review_source` 附理由标记。创建要求已自动关联其来源；
若显式评阅已登记要求，须先创建，再提供全部 requirement_ids。操作按顺序执行，
被拒绝的批次不会写入任何对象；修正指明的操作，以当前 revision 重新提交。来源覆盖仍是 Agent 判断，必须
对照原文独立检查，不能只审自己的计划。`research.material@1` 只适用于材料整理，
不能代替计算要求的科学验收。

用 `bind_requirement` 关联贡献证据的 Node。`revise_requirement` 只能增加范围，
不能删除或替换原始检查、约束、输入，也不能关闭 execution_required。模板原先
不可用时，安装后用相同 profile 身份 revise，明确采用该模板。

任务可用 `criteria` 自行组合与 Gate 相同的检查：`runtime_fact`、
`validator_result`、`agent_assessment`。计算任务设置 `execution_required=true`，
要求同一范围内的实际 Attempt 成功并完整收集；验证器运行不能代替请求的计算。
报告编写、解释和邮件交付使用 false，以明确的 criteria 核验报告 Artifact 和持久
交付回执，并与计算要求分开登记。已知的验收标准应在创建时声明，避免把执行
事实误当成科学验收。另声明如何检查科学交付，有注册验证器时优先使用。validator criterion 可用
`bindings` 指定必须匹配的值，不需要创建 profile。
Job 声明 `input_artifact_ids` 并在 `inputs` 暂存真实文件；Runtime 检查内容，
将输入证据版本绑定到 Attempt，不能只声明输入 ID 而不实际提供文件。

`assess_requirement` 消费 `result_receipt_refs`；Agent 判断通过 `assessments`
提供 criterion_id、verdict 与基于证据的 reason。模板未覆盖的任务约束需要评估
`requirement.constraints`。机器结论由实际证据推导，不能人工覆盖。科学解释及
需求提取是否完整仍需 Agent 判断，进程成功不能证明这两件事。

`mode=requirements` 显示当前覆盖和检查。空要求列表即使已评阅状态询问，也不会
报告 satisfied。阶段 Node 可先完成，修改 Gate 不能免除 requirement。
已完成交付的 requirement_consumption 保留当时版本和
验收；新证据或扩展范围使当前验收需重审，不改写历史交付。新 Attempt 会使旧失败停止
依据过期，必须重新判断。Claim 结论独立，完成约定分析后仍可为 inconclusive。

交付 Node 显式声明 `consumes.requirement_ids`、`consumes.artifact_refs` 或前置依赖。
`dependencies` 的每项为 `{node_id, condition}`；`completed` 要求 closed/completed，
`finished` 允许 closed/completed、inconclusive 或 stopped。blocked 不是 finished。已授权的阻塞或失败状态报告可用
`consumes.condition="observed"` 绑定当前范围；成功报告消费满足的要求。
邮件 prepare 绑定当前状态与事件，相关状态变化后必须重新 prepare。

`record_requirement_stop` 需要有来源的取消、匹配范围的执行失败或能力失败证据，
并保留未履行工作；`resume_requirement` 恢复该要求。没准备输入或尚未尝试不等于
能力不可用。缺可信预算记录时不能自行声称预算耗尽。terminal 表示本次运行已收束，
不等于所有科学工作成功；部分完成或取消时应报告未履行要求。缺少要求不能证明验收成功。

Artifact 类型字段优先使用持久 `artifact_ref`（如 `a1`）；`job_start` 可复用其之前
返回的 `prepared_ref`（如 `p1`）。准备器返回的是 `request_file` 和 `request_sha256`，
提交时原样传入这两个字段和 Node ID。短引用是工作区内不可重新绑定的精确索引，
不是哈希前缀猜测。请求或输入变更后生成新准备记录。陌生写入先查询
`mode=operations query=<操作名>` 获取完整字段。
