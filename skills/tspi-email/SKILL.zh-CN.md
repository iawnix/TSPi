---
name: tspi-email
description: 按配置发送 TSPi 研究事件和报告的邮件通知，并跟踪投递回执。
---

# TSPi 邮件通知

[English version](SKILL.md)

本 Skill 说明由 Host/Monitor 拥有的 `notify_send` 投递 capability；它不是 Root Agent
工具。研究状态使用
`tspi-research-kernel`，运行、报告与 Artifact 上下文使用 `tspi-orchestration`。通知传达
已记录的研究结果，并关联相应报告。安装级配置可以选择
兼容的 ClawEmail 传输，或内置 SMTP 传输；SMTP 当前支持 163 和 QQ 邮箱预设。

## 操作规则

- 使用安装级通知配置中的收件人。
- 将传输方式、发件人和凭据保存在安装级配置中；通知请求不能自行指定传输方式或收件人。
- 按投递接口选择事件类型和报告附件。
- 将投递回执保存在通知的运行历史中。
- 已知成功时复用回执；投递结果未知时，先查询供应商状态再决定是否重试。
- SMTP 必须使用 TLS（隐式 SSL 或 STARTTLS）和邮箱服务商提供的授权码。不得将邮箱密码或
  授权码写入工作区、请求、报告或日志。
- 本 Skill 只负责发送通知，不使用 POP3 或 IMAP。

请求格式、附件规则、回执身份和失败语义见
[email_delivery.zh-CN.md](references/email_delivery.zh-CN.md)。
