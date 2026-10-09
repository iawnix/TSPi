# Job Runtime

TSPi 使用通用 Job Runtime 执行科学计算。请求准备、已有结果的报告整理和邮件通过原生 bash 调用已安装 Skill 脚本。领域 Skill 描述命令、输入、预期输出
和解释标准，Root 使用 Job 与 Artifact 工具组合完成流程。

```text
job_probe -> job_start -> job_status -> job_collect
                         └-> job_cancel
                         └-> job_reconcile
```

`job_start` 接受任意 argv 向量和 workspace 相对工作目录，不需要科学工具注册表。
对于领域扩展声明的执行器，先通过原生 bash 准备入口，再将返回的 `request_file`、
`request_sha256` 与 `node_id` 传给 `job_start`。执行身份和参数已经固定在文件内，
提交时再添加 request_id 或 work_id 会被拒绝。其它输入形式以工具参数契约为准。
Job 创建持久化 receipt，并捕获 stdout 与
stderr。它不会选择科学方法、解析输出、验证 Claim，也不会自动创建 Finding。

任务运行时使用 `job_status`。Monitor 唤醒或服务重启后状态不确定时使用
`job_reconcile`。任务终态后使用 `job_collect`，它登记已声明输出并返回 Artifact 引用。
检查输出后，记录有意义的 Finding 并引用这些证据。导入数据、外部报告等未经过收集的
材料使用 `artifact_register` 登记。

Skill 可以描述 Gaussian、xTB、PySCF 或其他程序，也可以提供脚本和验证参考。这些
内容由 Root 在普通 Pi loop 中读取，不是 provider descriptor 或 capability gate。

进程成功退出只代表执行事实，不代表计算收敛、解析通过或 Claim 得到支持。
