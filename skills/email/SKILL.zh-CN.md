---
name: email
description: 通过配置的 SMTP 或 ClawEmail 发送用户要求的研究邮件，保存可恢复、可去重的发送回执。
---

# 邮件交付

例如“完成后给我发邮件”在收件人与内容明确时授权该次交付，不授权无关共享。通过原生 bash 使用 RESEARCH_AGENT_PYTHON 运行本 Skill 的 CLI；邮件交付不创建科学计算 Job。

1. 先用本 Skill 的 scripts/email_cli.py check 通过 RESEARCH_AGENT_NOTIFICATION_CONFIG 检查安装配置，再判断是否缺少设置。收件人来自配置；只说明解决问题所需的诊断，不暴露秘密值。
2. 生成并检查报告，在 reports/ 或 artifacts/ 下保存附件。草稿包含稳定 notification_id、event、subject、summary、report_refs。event 可选 progress、report_ready、calculation_failed、calculation_ambiguous、study_completed，描述内容必须符合实际结果与用户授权。
3. 执行 prepare 固定收件人、附件摘要和大小，此步骤不发送。核对 prepared.json 后，按用户授权执行 send。工具不校验科学完成条件；Agent 应诚实说明未完成工作。
4. 保存返回的 receipt_ref。sent 表示运输层接受，already_sent 返回原回执；unknown/sending 需核查，不能自动换 ID 重发。记录失败仅恢复记录，不再次发送。

研究笔记不参与发送准入。进度变化不会使已准备的附件失效；附件或收件人改变需要重新准备。相同 notification_id 的内容不能改变。详见 [交付协议](references/email_delivery.zh-CN.md)。

```text
"$RESEARCH_AGENT_PYTHON" <此 Skill 目录>/scripts/email_cli.py check --root <workspace> --output reports/email/config-check.json
"$RESEARCH_AGENT_PYTHON" <此 Skill 目录>/scripts/email_cli.py prepare --root <workspace> --request-file reports/email/draft.json --output reports/email/prepared.json
"$RESEARCH_AGENT_PYTHON" <此 Skill 目录>/scripts/email_cli.py send --root <workspace> --request-file reports/email/prepared.json --output reports/email/result.json
```
