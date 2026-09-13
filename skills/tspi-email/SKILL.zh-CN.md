---
name: tspi-email
description: 按配置发送 TSPi 研究事件和报告的邮件通知，并跟踪投递回执。
---

# TSPi 邮件通知

[English version](SKILL.md)

使用本 Skill 处理 `ts_notify` 和配置的邮件投递。运行时、报告、产物和状态合同使用
`tspi-orchestration`。通知传达已记录的研究结果，并关联相应报告。

## 操作规则

- 使用安装级通知配置中的收件人。
- 按投递接口选择事件类型和报告附件。
- 将投递回执保存在通知的运行历史中。
- 已知成功时复用回执；投递结果未知时，先查询供应商状态再决定是否重试。
- 将凭据和认证 URL 保存在私有安装配置中；消息和报告使用研究内容及产物引用。

请求格式、附件规则、回执身份和失败语义见
[email_delivery.md](references/email_delivery.md)。
