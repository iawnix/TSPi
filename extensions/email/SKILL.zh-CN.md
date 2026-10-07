---
name: email
description: 通过配置的 SMTP 或 ClawEmail 发送用户要求的研究邮件，保存可恢复、可去重的发送回执。
---

# 研究邮件

通过**本地** job_start 运行 [scripts/email_cli.py](scripts/email_cli.py)。通知配置、凭据和收件人由安装级配置管理，继承 TS_NOTIFICATION_CONFIG 或配置的安装路径。请求和异常恢复见 [投递规则](references/email_delivery.zh-CN.md)。

询问收件人前，使用继承的 TS_NOTIFICATION_CONFIG 在本地执行 `python <列出的Skill目录>/scripts/email_cli.py check --root <工作区> --output <工作区>/reports/email-check.json`。该检查只读配置，不发邮件；已启用且有效时沿用配置收件人，仅在配置缺失、无效或用户要求改地址时询问。用户无需在每条消息重写邮箱，交付问题不应阻止独立计算。

1. 核对用户已有通知授权和触发条件；同一授权无需重复询问，制定计划或单个 Job 完成本身不授权发送。
2. 生成报告并登记 Artifact。请求包含稳定 notification_id、event、subject、summary、report_refs。执行 `email_cli.py prepare --root <工作区> --request-file <草稿> --output <prepared.json>` 冻结内容及附件摘要，此操作不发邮件。
3. 通过 job_start 执行 `email_cli.py send --root <工作区> --request-file <prepared.json> --output <receipt.json>`，设置合理超时并声明回执输出；失败也收集回执。工作区与安装配置路径明确传入，不向远程暂存凭据。
4. 阅读回执：sent 表示传输接受，不等于已进入收件箱或已读；already_sent 复用既有回执；unknown 必须核查，不能盲目重试。用 `status --receipt-ref <工作区内回执路径> --output <status.json>` 查看状态。

Host/Monitor 只唤醒 Agent，邮件准备和投递由此 Skill 完成，不依赖原生通知工具或 Provider 注册。邮件失败不回滚计算。notification_id 不应包含 Job ID、重试时间或无关研究 revision。

使用本 Skill 处理上述请求。
