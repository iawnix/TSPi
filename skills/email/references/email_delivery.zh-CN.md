# 交付协议

notification_id 表示一次已授权的交付，不包含重试时间或笔记版本。report_refs 最多八个，指向 reports/ 或 artifacts/ 内文件。prepare 写入 ts-user-notification/2、配置收件人及附件摘要和大小。

发送库按逻辑身份加锁，先持久化 sending，再调用运输层，最后保存 sent/failed/unknown。发送尚未开始的失败可复用身份重试；结果不确定时先核查。密码轮换不会绕过去重。

回执保存在 reports/email/deliveries，发送完成后以规范回执身份保存运行事件，再投影到研究记录。投影失败的事件在下一次读取研究上下文时重放，不需要重新执行发送。事件持久化本身失败时显示 journal_error，发送回执仍是权威；用同一通知身份重试只恢复登记，不重发。可通过 status --receipt-ref 读取回执，如果已有交付 Node，可用 research_update 的 node_id 与 note 记录结果。
