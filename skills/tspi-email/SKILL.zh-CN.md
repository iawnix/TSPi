---
name: tspi-email
description: 在不暴露凭据且不改变科学状态的前提下，向固定目标发送由回执绑定的 TSPi 研究通知。
---

# TSPi 邮件通知

[English version](SKILL.md)

使用本 Skill 处理 `ts_notify` 和配置的邮件投递。运行时、报告、产物和状态合同使用
`tspi-orchestration`。通知只传达已记录结果，不创建或修改科学状态。

## 操作规则

- 读取安装级通知配置并使用固定收件人；Root 提供的 subject 或 summary 不能
  重定向投递。
- 只允许交付合同定义的版本化事件类型和报告包精确成员。
- 邮件回执属于运行来源记录，不是 Observation、Finding、接受记录或科学正确性的证明。
- 已知成功保持幂等；投递结果不明确时保持未决，不自动重试。
- 不得把凭据、私有 token 或认证 URL 写入工作区状态、提示词、报告或通知正文。

请求格式、附件规则、回执身份和失败语义见
`references/email_delivery.md`。
