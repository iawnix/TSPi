# t009 修复与验证

本次修复针对 t009 审查中的接口不匹配、接续责任缺失、同 Node 独立任务阻塞、准备请求字段丢失和远程排队诊断不足。没有恢复化学 Provider，也没有在 Skill 中引入独立生命周期状态库。

## 最终行为

- Host 的 next_run 固定映射到当前 Pi 正式接口 followUp；prompt/abort 同样使用正式接口，移除对动态 RPC 代理的 typeof 猜测。已知未准入错误与未知提交结果分开，保留原始 dispatch_error。迟到的有效准入响应保留真实 entry/operation ID。
- 带所属 session 的 continue_required checkpoint 由 State 生成持久 continuation；Host 经现有输入回执消费。Host 重启恢复相同请求身份，不重新规划科学工作。相同研究 revision 不重复唤醒；连续推进自动接续最多八次；跨轮无研究进展时返回 no_research_progress。外部等待、用户等待和终态不产生接续，失败/中止的 Pi 轮次也不会被自动重启。
- State 区分 eligible_node_ids（策略和依赖允许）与 ready_node_ids（没有运行 Attempt）。同一研究 Node 下的独立任务使用不同 workId；已有 workId 指向原 Attempt，先收集/对账。同一个 requestId 仍需由执行器验证不可变参数，不能覆盖旧提交。
- method-selection helper 支持 --output，输出 requestFile/requestSha256。job_start 校验工作区边界和摘要后完整传递请求，不允许混入 command 等覆盖字段。相同输入、方法、参数和配置生成稳定身份，主动新计算可以显式指定 --work-id。Attempt 保留 work_id、环境和脚本/配置摘要。
- job.toml 的 environment/backend submission 表承载 queue、resources 和可选 queue_wait_seconds，backend 覆盖环境默认值。科学 helper 的远程准备必须有明确队列，不能把 allowed_queues 当默认选择。示例配置选择 fata；现有安装不会被静默改队列。
- job_status 返回 scheduler_id/state、queue、等待时间、调度器 comment，以及配置 commands.checkjob 时的有界诊断文本。正常 Q/R 不再把缺少退出回执写成错误；可选 checkjob 失败不覆盖已知调度状态。配置等待阈值后，Monitor 仅生成一次 queue_wait_exceeded 事件，无变化不会周期性唤醒。
- 中英文 Skill 和运行边界同步了完整请求提交、共享 Node 工作身份、队列诊断和 State 接续约定。

## 验证

测试产物统一位于 `/home/iaw/debug/tspi-test-env/t009-repair`，短路径原生服务 fixture 位于同一测试根下的 `n`，结束时删除。没有向真实收件人发送邮件，没有重投或取消 t009 原作业。

- Python 回归 62 项通过：State/依赖准入、Job 恢复、Conda 绑定与队列选择、Monitor、排队诊断、文档契约，以及隔离 TLS SMTP 的 check → prepare → send → 幂等重试。
- Node 针对性回归 27 项通过：正式 Pi 方法映射、失败分类、请求文件防篡改、持久接续消费、checkpoint 修复、Monitor 投递等。
- 真实固定版本 Pi/Chord 集成通过，模型响应由本地确定性 fixture 提供：一条用户输入完成准备 → continue_required → 重启 Host → 自动恢复接续 → 从请求文件启动 Job → waiting_external → Monitor 完成事件投递 → 重复事件去重 → 收集结果 → 邮件配置检查 → 用户等待后停止。断言真实 entry_id 及 Attempt 中的工作身份/配置摘要。
- 同一集成流程在打包产物上通过，包含 current 符号链接入口。此测试验证真实执行与持久化边界，不冒充自由模型的六组科学任务评测。
- helper 的 --output 命令已执行，生成远程请求文件和摘要；没有提交该准备请求。
- 架构、Skill、公开术语 lint 与 git diff --check 通过。

## 安装与历史任务边界

源码验收完成时，交付物为源码修改和测试目录内的验证包，尚未切换 `/home/iaw/ResearchAgent` 的生产安装，也未提交/推送 Git。

安装时应在现有 `.pi/job.toml` 明确添加经确认的 `environments.remote.submission.queue/resources`；若需要调度原因和等待阈值，配置 `commands.checkjob` 与 `submission.queue_wait_seconds`。示例中的队列不是自动迁移授权。

旧 t009 中已经丢失原始派发错误的 uncertain 回执不会自动清除或换 ID 重放；这些历史记录需要根据实际 Pi submission 证据单独恢复。修复不能凭“没有结果”推断“从未提交”。本次没有重跑六组生产计算，也没有验证真实 SMTP 服务。
