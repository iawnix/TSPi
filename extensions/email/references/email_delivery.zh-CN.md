# 邮件投递合同

`notify_send` 把固定事件发送给 TSPi 安装配置拥有的收件人，并记录投递回执。

安装可以保留现有 ClawEmail transport，也可以使用内置 SMTP transport。SMTP 当前支持
`163` 与 `qq` preset：

```toml
[notifications.email]
enabled = true
provider = "smtp"
preset = "qq"                 # "163" or "qq"
recipient = "receiver@example.com"
from_address = "sender@qq.com" # optional; defaults to username
username = "sender@qq.com"
password_env = "TSPI_EMAIL_PASSWORD"
```

密码必须是提供商的 SMTP 授权码，而不是普通网页登录密码。`smtp.163.com` 与
`smtp.qq.com` 默认使用端口 465 和隐式 TLS；QQ preset 也接受端口 587 与
`security = "starttls"`。可以使用 password file 代替 `password_env`，但它必须是权限
0600 的绝对路径普通文件。Preset 固定 SMTP host；可选端口和安全覆盖仍由安装配置拥有，
通知请求不能提供这些值。

启用通知后，请求格式为：

```json
{
  "operation":"send",
  "event":"node_completed",
  "subject":"TS study update",
  "summary":"The bounded validation Node completed; connectivity remains open.",
  "reportRefs":["reports/final-study/final_report.md"]
}
```

允许的 event 为 `progress`、`node_completed`、`calculation_failed`、
`calculation_ambiguous` 和 `study_completed`。附件必须是
`reports/<packageName>/` 下准确列入 `ts-report-package/5` manifest 的现有普通文件。
`nodes/` 下的 Render 文件必须先通过逻辑 Artifact ID 纳入报告包。

在安装级配置收件人与凭据。Host 写入摘要绑定的回执，并对重复的成功请求返回同一回执。
投递结果未知时，重试前先检查 provider 状态。投递失败记录在通知运行历史中。

本 Skill 只负责发送。POP3 与 IMAP 不在范围内；未来工作流若需要读邮件，应增加独立的
接收/mailbox capability。
