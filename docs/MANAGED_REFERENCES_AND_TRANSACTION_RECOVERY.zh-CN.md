# 受管引用与事务恢复索引

## 受管准备请求

`job.prepare({request_file})` 读取工作区内的请求文件，保存不可变请求快照、原文件摘要、输入内容摘要和工作身份，返回 `prepared_ref`（例如 `p1`）。这一步不提交 Job，也不创建 Attempt 或科学结论。

化学扩展的 `method-selection/scripts/prepare_job.py --output <workspace>/request.json` 会自动查找输出路径所属的工作区并登记引用；可用 `--root <workspace>` 显式指定。工作区外的独立准备保留 `request_file` / `request_sha256` 输出。

后续工具调用为 `job_start({prepared_ref: "p1", node_id: "node_ts"})`。引用由 State 解析，Host 不自行读取或猜测别名。请求内容、输入、环境及工作身份不可在提交时覆盖；可传入 Node、超时及显式重复计算信息。修改请求文件不会改变已有引用，重新准备产生新的引用；输入内容发生变化后，旧引用会被拒绝，需重新准备。改变计算内容时仍须使用与新内容对应的工作身份，不能复用旧 request_id 来覆盖已提交工作。

引用采用工作区内共享的单调计数器和明确类型：`pN` 是准备请求，`aN` 是 Artifact。它们不是哈希前缀，不作模糊匹配，也不会因排序变化重新绑定。同一引用的重复提交沿用现有 Job Runtime 的工作身份、并发提交及幂等回执规则；提交结果不明确时仍要求先核对原工作，不能自动重投。

## Artifact 引用

Artifact 注册到规范 State 后，Evidence API 返回稳定的 `artifact_ref`。`artifact_read`、`artifact_link` 可使用 `artifact_ref`；原 `artifact_id` 参数及 ChangeSet 的证据引用字段也接受精确 `aN`。同时提供两个 selector 时，必须解析到同一 Artifact。

ChangeSet 仅展开明确的证据字段，不改写 statement、说明文本或对象自身的 ID。不存在的引用返回错误及已登记候选，不自动纠正。读取投影只显示已有引用，不在读取时分配新编号。规范 Artifact ID、摘要、来源及生产 Attempt 仍保存在 State，别名不增加科学权限。

注册表位于 `operations/references/index.json` 及 `operations/references/records/`。注册表与快照的写入共用工作区锁及事务 redo 恢复边界；它们不是可随意删除的缓存。

## 事务日志版本 2

旧实现每次获得工作区外层锁都会解析全部历史事务。现在仅首次升级扫描历史日志；后续读取检查固定版本标记和 `operations/transactions/recovery/pending/` 内尚需恢复的记录。已完成日志保留在原位置，原请求 ID 的幂等查询不变。

提交顺序为：准备回执 → 持久化恢复指针 → 持久化 committing 决定 → 写入文件 → committed 回执 → 删除指针。指针本身不能授权提交。若中断时回执仍为 prepared，恢复只删除指针；若为 committing，则重放；若为 committed，则只清理残留指针。新建目录条目也执行 fsync，防止决定已持久化而恢复目录尚未持久化。

Python 可读 `agent_transaction/1` 与 `/2`，新写入使用 `/2`。首次升级在事务目录写入 `writer-version.json`；旧版本写入器会拒绝该标记，避免在已启用索引后产生无索引的 committing 决定。

**部署前必须停止所有旧工作区写入进程，再启动新版本。不能对已升级的工作区直接运行旧版本或删除版本标记来降级。** 如需回滚，应恢复升级前的一致备份，或另行实施并验证迁移；不能把未完成恢复指针当作缓存清理。此实现及其测试不会部署生产服务。

测试覆盖：并发/重启复用引用、请求与输入版本漂移、篡改快照、引用类型与工作区隔离、重复真实 Job 提交、登记中断恢复；以及决定前中断、部分文件写入、残留指针、升级中断、缺失回执和 500 条历史日志下的固定读取次数。测试使用微型进程与样例数据，不替代真实化学计算验收。
