# t006 工作流可靠性修复（2026-10-08）

本记录对应 10 月 8 日的 t006，会话 `c49429ed-0728-4be3-80b3-5568b928eb6b`，审查安装版本为 `0.18.0-sha256-002ca76be825ee85`。10 月 6 日同名工作区的旧修复记录不作为本次验收依据。

## 修复结果

| 问题 | 实施行为 |
| --- | --- |
| 缺 Gate 的提交先暂存，拒绝后留下孤儿目录 | 新 Job 在暂存前检查 Node 准入和完成条件；暂存带请求摘要及归属记录；确认未提交的失败清理暂存，同请求可重试。 |
| 暂存/事务中断后不能区分是否提交 | 有归属且没有提交意图的暂存可恢复；已准备或提交的事务先恢复持久决定，结果不明时返回 unknown；未知归属目录保留并要求核查。 |
| 启动后回执保存失败被当成未执行 | 返回 `submission_ambiguous`，携带 Job/Attempt 和 `job_reconcile` 恢复提示；工具错误明确 action_outcome=unknown，禁止自动重提。 |
| 邮件节点关闭失败，误诊为计算 Gate 失败 | 原子批次错误返回 operation_index、operation_type、target_id、atomic_batch_committed=false；整批仍保持原子回滚。 |
| 某些操作顺序能制造无效完成状态 | 关闭 completed 节点检查已完成依赖；整批完成后检查新增的不变量违规。运行时收集发现旧证据失效仍可如实登记，并允许后续修复。 |
| Agent 猜测 Gate 字段、错误信息混淆 | JS 工具、Python 校验、operations 查询共用 gates.json 中的嵌套合同；支持 query=evaluate_gate；区分 verdict 与 reason 错误。 |
| artifact_link 接受任意字符串、运行时才拒绝 | 工具与 State 共用证据关系枚举。Gate 评估保存引用 Artifact 的摘要版本。 |
| 邮件依赖未完成也能通过 Skill CLI 发出 | 研究工作区发送请求需 node_id；首次发送在 State 锁内检查生命周期、节点依赖、策略和完成条件，再保存 sending 记录。check/prepare 可提前执行。 |
| 部分邮件异常错误地允许自动重发 | 进入传输后未分类异常按 unknown 处理；遗留 sending、历史 delivery_failed 要求核查；ClawEmail 已执行后的清理错误也标为不确定。 |
| 同 notification_id 改内容会发送第二封 | 按逻辑身份跨进程加锁；相同内容复用回执，改变内容要求新的 notification_id。已发送请求可在节点或范围关闭后复用回执。 |
| xTB 多余 --method 提交后才失败 | 三种 runner 提取纯 CLI 参数合同，准备脚本复用它们，在写请求前拒绝未知参数和覆盖受管路径的参数。 |
| 报告把方法名当成 Environment | 新增 `--job <job-directory>`，从 Job 记录读取环境及结果路径；独立 `--result environment=path` 保留且明确左侧语义。 |

## 编排与职责

独立方法/环境建立独立计算 Node，报告与邮件通过 dependencies 的条件连接。普通节点无需 Gate；需要正式评估边界时才声明 Gate。

科学结果由方法 Skill 验证；Agent 登记、解释证据并评估 Gate。邮件仍通过 email Skill CLI 运行，不引入邮件 Provider 工具或计算 Attempt。发送后由 Agent 将实际持久 receipt_ref 注册为 Artifact，核验回执、评估交付 Gate、关闭 Node，最后提交 terminal。

若发送已成功而 State 登记失败，恢复动作是补登记和收尾。相同发送请求复用原回执。任意自编 bash 不属于受管理发送入口；不能将 Skill CLI 的准入机制描述为对任意 shell 命令的强制拦截。

## 验证与证据

所有测试环境与日志位于 `/home/iaw/debug/tspi-test-env/t006-fix`。

- Python 单元及合同测试：257 项通过，`logs/pytest-verified.log`。
- Node 工具合同、Python bridge、生命周期、扩展加载及 prepared Job 定向测试：46 项通过，`logs/node-verified.log`。
- 安装包清单检查通过，`logs/package-verified.log`。
- public surface、architecture、skills lint 均通过，`logs/lint.json`。

新增或扩展用例包括：

1. 缺 Gate 拒绝不暂存；补 Gate 后原请求可提交。
2. 暂存失败、暂存进程中断、事务 prepare/commit 中断及启动后回执提交失败。
3. 并发同请求仅启动一次；不确定提交复用原身份。
4. 批次第三项失败精确定位邮件节点；前两项单独提交成功。
5. 关闭后又添加未通过 Gate 的批次被最终不变量检查拒绝。
6. 真实 Job 进程输出 → 报告 → 隔离 TLS SMTP 服务 → 回执 Artifact → 交付 Gate → terminal；重复请求仅投递一次。科学结果使用 fixture，本测试不声称完成新的科学方法实算。
7. 邮件传输异常、接受后回执保存失败、并发发送、同身份内容变化和 ClawEmail 清理失败。
8. 参数错误在准备阶段拒绝；从 Job 记录推导报告环境。

测试 SMTP 服务在 finally 中 shutdown/server_close/join，测试 Job 均完成或取消；临时工作区由测试清理，保留日志。生产安装、原 t006 状态及其历史邮件回执保持原样。

## 后续部署边界

本次交付为源码修复及自动验证。尚未部署生产安装，也未通过真实模型重跑整条研究会话。部署后恢复原 t006 时，应复用已有三个计算结果和 sent 回执，补齐交付 Gate 与证据登记；已有未知归属暂存目录保留审计后单独处理，不能自动重算或重发历史邮件。

SMTP 接受与本地持久化之间不存在跨系统原子提交；发送后回执丢失仍以 unknown 保守处理，不承诺绝对恰好一次投递。
