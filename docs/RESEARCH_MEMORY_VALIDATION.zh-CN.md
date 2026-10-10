# Research Memory 重构验收记录

日期：2026-10-09。状态：本地实现与回归验收完成；未部署到生产或迁移已有工作区。

设计依据为 [Research Memory 整体设计与实施计划](RESEARCH_MEMORY_DESIGN_AND_IMPLEMENTATION_PLAN.zh-CN.md)。本记录描述当前工作树的实际验证，不沿用旧实现的通过数量。

## 已落地的合同

- 一个 `research_agent.research` Python namespace 和一个 `runtime-bridge` 运行命令入口。旧 `research_state`、旧 bridge、全局 progress 协议及研究生命周期工具已删除；发布清单禁止旧实现进入包。
- Workspace manifest 为 `research_workspace/2`。Host 创建、登记与附着工作区；Memory 保存研究内容，Job、Artifact、Monitor 和邮件分别保留自己的权威回执。
- Node 持续承担一个问题，多次尝试追加在同一 Node。当前字段来自不可变变更记录的投影；修改当前判断受版本与实际读取依据保护。
- Result 不可变，固定输入、证据、材料和实际计算方案版本。修正使用 supersedes；发布 Result 不自动关闭 Node，也不自动替代综合判断。
- part_of、requires、alternative_to 明确持久化；反向查询由系统提供。确证输入生成 uses，读取本身不生成使用关系。相互依赖仅产生诊断，不能成为基础工具准入条件。
- 模型只使用 research_read、research_search、research_create、research_update、research_result。source 和 observe 是内部来源及读取确认入口。
- 读取依据只确认实际提供的内容。过大工具回复保留提交结果与读取入口，不确认被省略字段；字段分页仅在同一版本、同一内容的所有区间都被确认后，才允许相应替换。对称关系两端的并发修改也检查关系内容依据。
- journal、map、Node 视图、SQLite 检索与 Markdown 可重建。`workspace.py doctor/rebuild` 提供诊断与修复；修复不修改原始研究内容、材料或执行回执。
- Monitor 使用 v2，next_run 在内部认证准入中实际生效。忙时不插入输入；固定事件批次、投递身份与消费回执独立于 Memory sequence。
- 自动执行暂停通过 Monitor disable/enable 实现：继续观察并保留事件，恢复后沿用原投递身份；不会取消已经接收的回合。Node paused/closed 不等同于暂停 Monitor，也不取消 Job。
- 运行与邮件事实进入持久事件投影。Memory 投影失败不触发重新计算或重新发送邮件。
- Skill 使用 Pi 原生加载，资源目录与摘要一致；核心 Skill 改为 research-memory。CLI、TUI、Web 使用新协议；Context 展示不含 `≈`。

## 验证结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 完整 Python 回归，构建并安装临时 wheel 后运行 | 546 通过 | `/tmp/memory-wheel-final-verification.log` |
| pinned Pi 原生完整回归 | 167 通过，0 跳过 | `/tmp/memory-native-final-verification.log` |
| TypeScript 与生成工具类型 | 通过 | `tsc --noEmit`、`update_tool_types.mjs --check` |
| 公开工具文档生成一致性 | 通过 | `update_public_contract.mjs --check` |
| 架构、公开术语、Skill 资源检查 | 通过 | 对应 lint；16 个 Skill |
| 包清单与删除边界 | 通过 | `scripts/check_package.py` |
| 差异空白检查 | 通过 | `git diff --check` |

后续清理说明：2026-10-09 用户明确要求删除旧测试环境，以下历史路径已不可用；本记录不代表新测试根已经重建或重新验收。

wheel 测试环境记录：`/home/iaw/debug/coragent-test-env/test-results/source-test-0352688781020e92.json`。测试安装、环境和工作目录均位于指定测试根目录。原生测试的 Host/Worker/Monitor 服务已退出；邮件测试的本地 SMTP 服务由 teardown 关闭。

## 关键行为的实际覆盖

| 风险 | 对应测试 |
| --- | --- |
| 原始消息被摘要覆盖、重试产生重复 Node/Result | `tests/unit/test_research_memory.py` |
| 多次尝试错误地拆成多个 Node，或后台事实造成判断冲突 | `tests/unit/test_research_memory.py` |
| 读取/搜索制造关系，环造成整个系统不可用 | `tests/unit/test_research_memory.py`、`test_research_memory_integrity.py` |
| 旧方案计算被解释为新方案结果 | Job 绑定测试及 `test_result_retains_job_fact_original_proposal_revision` |
| Result 已保存但展示失败被误报为全失败 | `test_generated_view_failure_reports_saved_result_without_republication` |
| 三个不同发布边界崩溃后出现半份 Result 或重复产出 | `tests/unit/test_research_memory_integrity.py` |
| 原始记录或 Result 误改被重建当成合法来源 | 内容摘要和重建完整性测试 |
| 长中文内容截断后错误地允许覆盖未读字段 | Python 分页覆盖测试及真实原生工具超大回复测试 |
| 1,000 Node / 10,000 记录中关键问题被噪声挤掉 | 大规模候选排序、分页、规范记录重放测试；预热搜索断言不重新读取记录正文 |
| 相同字节被伪认成另一份科学材料来源 | `tests/unit/test_execution_memory_binding.py` |
| Memory 故障导致重复执行、漏掉终止事件 | 运行 outbox、投影重放、关闭 Node 与无关联 Job 测试 |
| next_run 只是字符串，没有调度作用 | 原生 Monitor/Host 忙闲、暂停恢复、认证与输入去重测试 |
| Worker 重启后不能恢复真实研究 | 创建 Node→关联 Job→重启→Monitor 唤醒→收集材料→发布 Result 的原生 Worker 测试 |
| 邮件成功后 Memory 失败导致重发 | 邮件回执去重、持久投影重放和本地 TLS SMTP 集成测试 |
| 源码可用但发布包缺模块或 Skill 资源 | wheel 来源校验、发布包清单、安装/组件和原生 Skill 读取测试 |
| 修复函数存在但 CLI 不可调用 | `tests/integration/test_workspace_cli.py` 的删除 map 后 rebuild→doctor 往返测试 |

## 验收范围

原生验证使用实际 Pi/Host/Worker 与受控模型回复，证明工具、持久化、重启和调度合同。它不等同于外部模型完成一整项科学研究的效果评估。未执行生产部署、真实外部邮件或新的远端计算任务。

第一版保留设计中明确的范围：不自动迁移旧工作区，不加入向量数据库、跨工作区裸引用、自动科学通过判定或由 Node open 触发的无限续行。关系图用于组织与检索，执行调度仍以确证事件为依据。
