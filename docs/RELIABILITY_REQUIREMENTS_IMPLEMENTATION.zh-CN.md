# t008 / t009 可靠性与验收修复实施记录

继 `697b8160` 的 Claim 验收、上下文预算与诊断修复之后，本次落实原设计中的用户交付要求、有限科学验收、交付消费、精确引用及事务恢复优化。Research State 保持唯一规范状态，未引入第二个工作流引擎。

## 已落实的行为

- **原始要求不随计划消失。** Host 从真实 Pi Submission/Entry 保存用户来源；单个或批量 Monitor 唤醒、State 接续、模型生成消息不算用户要求。普通输入不能占用内部请求 ID 前缀。首次来源记录失败会阻止推进，成功记录后缓存本次 Worker 已处理的 Submission。
- **验收与科学结论分离。** `requirements` 保存来源原文、约束、输入、贡献 Node 与安装 profile。`review_source`、`create_requirement`、`bind_requirement`、`revise_requirement`、`assess_requirement`、`record_requirement_stop`、`resume_requirement` 为公开操作；`sources`、`profiles`、`requirements` 为读取模式。最低检查不能删减，方法和输入不能被无关回执替代，Gate 不能免除要求。
- **当前证据决定当前验收。** 验证回执绑定输入 Artifact、producer 的当前 result receipt、方法、电子态、核数和内存；platform 约束由所有相关科学 producer 的实际环境核对。证据或范围变化使验收需重审。阶段 Node 可先完成，Claim 可在完成分析后仍无结论。
- **历史交付不冻结研究。** 完成交付保存当时的 requirement 版本和 assessment。扩展范围或登记新证据可继续推进；旧交付事实保留，新的成功交付及终态仍检查当前要求。
- **停止不等于成功。** 有来源的用户取消、匹配范围的执行失败或能力失败可停止；未履行要求保留。新增 Node/Attempt 或重试使旧停止失效。没有可信预算记录时，不支持凭 Agent 自报预算耗尽停止。旧工作区缺少 requirements 明确显示未跟踪，不能据此发送 study_completed。
- **依赖与通知使用同一状态。** `completed` 与 `finished` 条件共用判定函数；blocked 不算 finished。通知声明消费的要求、Artifact 或前置 Node。prepare 绑定事件、来源节点状态、产物版本和实际结果；send 重新核验。失效准备必须重建，已有 sent/unknown 仍保持幂等且不自动重发。
- **缩短引用而不降低校验。** `prepared_ref=pN` 保存不可变请求与输入摘要，`artifact_ref=aN` 为持久精确索引；没有哈希前缀猜测。并发和重试仍复用同一执行身份。State 写工具不再重复返回整份 summary。
- **保留故障诊断能力。** 当前 State 不可读取时，仅本地 read/system_prompt 可用于诊断，执行和写入拒绝使用缓存准入。yield 检查失败时保存诊断答复，不伪造 checkpoint；已得到的合法 follow-up 不因维护失败丢失。内部接续通过 Pi 原子准入，丢响应和重启后按原身份恢复。
- **控制日志读取成本。** 事务日志升级为 v2，首次扫描旧历史，之后只检查未完成提交指针。覆盖提交决定前后、部分写入、残留指针及迁移中断的恢复行为。

## 科学路径与验证范围

化学扩展实现一条有边界的路径：显式映射的 Diels–Alder 反应 → 有限 RDKit 立体/构象候选 → Gaussian QST2/Freq 输入 → 正反 IRC 输入。候选清单保留成功和失败分支、原子顺序及输入摘要。

三项独立注册验证器分别检查映射变换、鞍点/成键模式、双向 IRC 连通性。t009 中产物图相同但原子对应错误的输入不能通过 DA 拓扑检查。缺失完整收敛、频率不完整或非有限、无关虚频、方法/资源不符、错误 IRC 起点、两个方向进入同一盆地均不能通过。

支持范围详见 [Gaussian 路径参考](../extensions/chemical/skills/candidate-generation/references/gaussian_path.zh-CN.md)。这不是通用或穷尽的机理搜索，不能证明所有立体异构体或构象已覆盖。端点连接检查不等于一般键级恢复或立体机理证明。不支持的 Gaussian 输出格式保持未通过/需检查。

## 验证

- Python 单元、公开合同与集成：**590 passed，1 skipped**。
- 完整 Native Pi：**255 passed**，包括真实 Worker、重启、内部消息排除、接续丢响应恢复和故障最终答复保存。
- 类型检查、public/architecture/Skill lint、包清单检查通过。
- 科学链路调用真实候选 helper、Job Runtime、Gaussian runner、parser 和注册 validator；solver 输出是明确标注的合成 fixture。**没有执行真实 Gaussian 科学计算或真实大模型评测**，不能据此承诺实际候选收敛或模型自然语言覆盖率。
- 测试安装、临时工作区均使用 `/home/iaw/debug/tspi-test-env`。隔离 SMTP、Native 服务及测试 Job 在测试结束后清理，没有生产邮件或部署。

## 升级及可信边界

事务日志 v2 启用前必须停止全部旧工作区写入进程；不能对已升级工作区直接运行旧版本或删除标记降级。操作顺序及恢复说明见 [受管引用与事务恢复](MANAGED_REFERENCES_AND_TRANSACTION_RECOVERY.zh-CN.md)。本次仅提交推送，不升级生产工作区。

自然语言要求是否抽取完整、取消语句的含义、报告正文与科学解释仍需 Agent 审查。代码验证来源、版本和已声明的有限标准，不声称证明科学真理。系统保留可信的一般 shell；这些规则约束受管执行与验收，不是针对恶意任意 shell 修改的隔离安全边界。导入文献和数据仍可作研究证据，但不能冒充要求 collected_output 的计算回执。
