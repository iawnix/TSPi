# 请求与恢复

草稿包含稳定 notification_id（用户请求/事件/报告身份）、event、subject、summary 和 report_refs（最多八个工作区 reports/ 或 artifacts/ 下的文件）；研究工作区还需交付节点的 `node_id`。prepare 固定 ts-user-notification/2、配置收件人、附件摘要和大小，并保存报告范围的 `state_binding`。报告或消费状态改变需重新准备请求。

用交付节点的 `consumes.requirement_ids`、`consumes.artifact_refs`、类型化 `dependencies` 或其组合声明范围；空声明不能建立独立通知。`consumes.condition` 默认 `satisfied`；对未履行工作的已授权状态通知使用 `observed`。Artifact 引用指实际登记证据，附件路径另放 `report_refs`。计算材料及派生输入必须属于生产 Attempt 当前收集结果。

| 事件 | 准备及首次发送时检查的状态断言 |
| --- | --- |
| `progress` | 报告所声明范围的当前状态；未履行要求使用 observed。 |
| `node_completed` | 全部显式前置节点为 closed/completed，不代表整个研究通过验收。 |
| `calculation_failed` | 消费范围内有已确认 failed/timed_out 的 Attempt，无关失败不能代替。 |
| `calculation_ambiguous` | 消费范围内有 unknown 或执行冲突的 Attempt。 |
| `study_completed` | 全部已跟踪用户要求当前满足；observed 或未跟踪范围不能证明研究成功。 |

成功交付例如使用 `consumes: {requirement_ids: ["requirement_path"]}` 及 `completed` 前置依赖。已授权的失败通知使用 `consumes: {requirement_ids: ["requirement_path"], condition: "observed"}` 和 `dependencies: [{node_id: "node_ts", condition: "finished"}]`。finished 前置节点必须实际 closed，blocked 不是终态；保留其真实失败/无结论 outcome。“完成后发结果”本身不授权失败通知。

绑定包含消费来源节点状态、requirement 验收、所选 Artifact 版本和生产结果回执。来源改变会拒绝旧准备请求；读取变化后重新 prepare，不手工修改绑定或把节点假报 completed。前置节点完成前准备的 progress 在其关闭后需要重新准备；node_completed 不能在断言尚未成立时准备。已成功发送时，重放原请求恢复回执，不另准备身份重发。

安装配置保存 TLS 设置和凭据引用。`check --root ... --output ...` 不发送邮件；凭据不得进入 argv、请求、报告或日志。send 在调用传输前再次验证收件人和附件。

回执和锁保留在 reports/email/deliveries 下。稳定身份支持跨 bash 调用和无关 research revision 去重；轮换密码不应再次发送。遇到同事件、同主题的旧版回执时，因无法证明完整内容身份，必须先核查。升级与回滚均保留旧回执。

SMTP DATA 后断连或进程崩溃可能留下 unknown。SMTP 没有通用投递查询接口，确定性 Message-ID 也不保证恰好发送一次。先检查已有回执，只有传输真正支持状态查询时才查询。sent、sending、unknown 不自动重发；确认未发送的失败修复原因后可以重试。传输接受不等于已送达收件箱。

新发送要求交付节点具有完成条件、所需策略、已满足的类型化依赖，并通过 State 准入；finished 依赖不绕过全局 blocked/terminal。可采用“登记的回执证实传输服务接受获授权报告”作为条件；sent 仅表示传输接受。登记 send 返回的持久回执路径，将真实 artifact_ref 或 artifact_id 引入 evaluate_gate.evidence_refs。回执保留准入时绑定，不创建计算 Attempt。

发送器跨进程串行处理 notification_id：相同内容复用 sent 回执，同一身份修改内容会被拒绝。进入传输后出现未分类异常、遗留 sending 或历史 delivery_failed 回执均需核查，不能作为未发送的证明。
