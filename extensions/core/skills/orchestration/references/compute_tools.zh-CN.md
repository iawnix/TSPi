# Job Runtime

TSPi 使用通用 Job Runtime 执行长时间任务。领域 Skill 描述命令、输入、预期输出
和解释标准，Root 使用 Job 与 Artifact 工具组合完成流程。

```text
job_probe -> job_start -> job_status -> job_collect
                         └-> job_cancel
                         └-> job_reconcile
```

`job_start` 接受任意 argv 和工作目录，创建持久化 receipt，并捕获 stdout 与
stderr。它不会选择科学方法、解析输出、验证 Claim，也不会自动创建 Finding。

任务运行时使用 `job_status`。Monitor 唤醒或服务重启后状态不确定时使用
`job_reconcile`。只有任务进入终态后才能使用 `job_collect`。每个有意义的输出都
应使用 `artifact_register` 注册，再通过 `research_change` 创建 Finding，并引用
对应 Artifact。

Skill 可以描述 Gaussian、xTB、PySCF 或其他程序，也可以提供脚本和验证参考。这些
内容由 Root 在普通 Pi loop 中读取，不是 provider descriptor 或 capability gate。

进程成功退出只代表执行事实，不代表计算收敛、解析通过或 Claim 得到支持。
