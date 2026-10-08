---
name: email
description: 通过配置的 SMTP 或 ClawEmail 发送用户要求的研究邮件，保存可恢复、可去重的发送回执。
---

# 研究邮件

所列 SKILL.md 位于 `extensions/email`；CLI 相对于包根的路径是 `extensions/email/scripts/email_cli.py`。以当前 SKILL.md 所在目录解析脚本链接。

通过 Host 本地原生 **bash** 运行 check、prepare、send、status 四种操作，调用 [scripts/email_cli.py](scripts/email_cli.py)。通知配置、凭据和收件人由安装级配置管理，继承 TS_NOTIFICATION_CONFIG 或配置的安装路径。请求和异常恢复见 [投递规则](references/email_delivery.zh-CN.md)。

询问收件人前，使用继承的 TS_NOTIFICATION_CONFIG 在本地执行 `"$TSPI_PYTHON" <列出的Skill目录>/scripts/email_cli.py check --root <工作区> --output <工作区>/reports/email-check.json`。该检查只读配置，不发邮件；已启用且有效时沿用配置收件人，仅在配置缺失、无效或用户要求改地址时询问。配置预检可在计算前运行，不依赖结果交付节点就绪。用户无需在每条消息重写邮箱，交付问题不应阻止独立计算。

1. 核对用户已有通知授权和触发条件；同一授权无需重复询问，制定计划或单个 Job 完成本身不授权发送。
2. 生成报告并登记 Artifact。请求包含稳定 notification_id、event、subject、summary、report_refs。执行 `email_cli.py prepare --root <工作区> --request-file <草稿> --output <prepared.json>` 冻结内容及附件摘要，此操作不发邮件。
3. 通过 bash 执行 `email_cli.py send --root <工作区> --request-file <prepared.json> --output <receipt.json>`，设置合理超时，请求和输出保存到工作区 reports/email；失败或超时也检查持久化回执。不为邮件创建 Job 或计算 Attempt。工作区与安装配置路径明确传入，不向远程暂存凭据。
4. 阅读回执：sent 表示传输接受，不等于已进入收件箱或已读；already_sent 复用既有回执；unknown 必须核查，不能盲目重试。用 `status --receipt-ref <工作区内回执路径> --output <status.json>` 查看状态。

Host/Monitor 只唤醒 Agent，邮件准备和投递由此 Skill 完成，不依赖原生通知工具或 Provider 注册。邮件失败不回滚计算。notification_id 不应包含 Job ID、重试时间或无关研究 revision。

使用本 Skill 处理上述请求。

完成已授权交付或记录其具体阻塞后再写 terminal checkpoint。交付 Node 记录结果，不需要计算 Attempt。遵守用户授权和完成条件：“完成后发结果”不自动授权失败通知。全局 blocked/terminal 仍会阻止 bash；先通过显式恢复 checkpoint 再继续。

研究工作区的草稿必须包含已有交付节点的 `node_id`。首次发送前声明其完成 Gate，并关闭已完成的依赖节点。CLI 在持久保存 sending 记录时检查 State 准入；check/prepare 可在依赖未完成时运行。节点或范围关闭后，重放 sent 请求仍返回已有回执。

send/status 后，通过 artifact_register 将持久 `receipt_ref` 登记到交付节点，读取并核验，用返回的 artifact_id 填写 Gate 的 evidence_refs。代理评估字段为 criterion_id、verdict、reason。评估 Gate 并关闭节点后再写 terminal。登记失败只恢复登记，不重发邮件。内容改变须在用户授权的交付范围内使用新的 notification_id。
