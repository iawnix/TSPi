# 请求与恢复

草稿包含稳定 notification_id（用户请求/事件/报告身份）、event（progress、node_completed、calculation_failed、calculation_ambiguous、study_completed）、subject、summary 和 report_refs（最多八个工作区 reports/ 或 artifacts/ 下的文件）。prepare 固定 ts-user-notification/2、配置的收件人、附件摘要和大小。内容改变需重新准备请求，不能悄悄修改已授权内容。

安装配置保存 TLS 设置和凭据引用。`check --root ... --output ...` 不发送邮件；凭据不得进入 argv、请求、报告或日志。send 在调用传输前再次验证收件人和附件。

回执和锁保留在 reports/email/deliveries 下。稳定身份支持跨 bash 调用和无关 research revision 去重；轮换密码不应再次发送。遇到同事件、同主题的旧版回执时，因无法证明完整内容身份，必须先核查。升级与回滚均保留旧回执。

SMTP DATA 后断连或进程崩溃可能留下 unknown。SMTP 没有通用投递查询接口，确定性 Message-ID 也不保证恰好发送一次。先检查已有回执，只有传输真正支持状态查询时才查询。sent、sending、unknown 不自动重发；确认未发送的失败修复原因后可以重试。传输接受不等于已送达收件箱。
