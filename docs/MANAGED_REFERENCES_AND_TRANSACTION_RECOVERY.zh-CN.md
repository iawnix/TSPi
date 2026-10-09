# 受管引用与事务恢复

准备器 `python -m tspi_runtime.executors` 仅生成请求文件和摘要，不写研究状态。
Agent 通过 `job_start({request_file, request_sha256, node_id})` 提交。Runtime
一次读取并核对文件、输入与环境，再在 State 事务中登记不可变准备引用、Attempt
和提交意图。返回的 `prepared_ref` 可供同一工作重试复用。

请求内的 request_id、work_id 和执行参数不得通过额外工具参数覆盖。改变参数时
重新准备；原请求重试查询和复用原工作，不因响应丢失产生第二个计算。

`pN` 是准备请求，`aN` 是 Artifact 的工作区内精确持久引用，不是哈希前缀。
同一引用不能重新绑定；读取不分配新编号。Artifact 的规范 ID、摘要、来源和
生产 Attempt 仍由 State 保存。注册表位于 `operations/references/`，共用
工作区锁和事务恢复边界。

当前写入器只读写 `agent_transaction/2`，并要求 writer version 3 和当前
recovery index。初始化新工作区时创建版本标记。旧工作区、事务或会话不会被
扫描、转换或自动恢复；安装使用新工作区，不提供旧格式迁移。

当前协议下的事务提交顺序为：准备回执 → 持久化恢复指针 → committing 决定
→ 文件写入 → committed 回执 → 删除指针。恢复只检查 pending 指针：prepared
没有提交权限，committing 重放已决定的写入，committed 清理残留指针。
目录项同样执行 fsync。已完成事务仍保留原请求身份和幂等回执。

外部计算及邮件副作用不由文件事务回滚。Job 用原进程或调度器身份协调，邮件
sent/unknown 回执禁止盲目重发。恢复索引和副作用回执均不能当作缓存删除。

回归覆盖并发和重启复用、请求及输入漂移、篡改快照、提交中断、部分写入、
残留指针和缺失回执；真实科学执行及安装验收另见整改计划中的证据记录。
