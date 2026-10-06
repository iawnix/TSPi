# Pi Runtime Adapter

Pi 提供唯一的模型与工具循环。TSPi 在此基础上增加 Research State 上下文、Job
Runtime 和 Artifact Runtime，不创建 Compute 或 Review 子 Agent。

Root 使用：

```text
research_read
research_change
research_strategy
research_interpretation
research_checkpoint
job_start / job_status / job_collect / job_cancel / job_reconcile
artifact_register / artifact_create / artifact_read / artifact_derive / artifact_link
```

领域 Skill 描述命令构造和输出解释方式。Root 使用普通 Pi 工具组合这些步骤，并
把证据写入 Research State。Job 完成只代表执行收据存在；必须先把原始输出注册为
Artifact，再解释为 Finding。
