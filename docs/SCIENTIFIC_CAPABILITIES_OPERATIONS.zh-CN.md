# 科学执行与运维

[English](SCIENTIFIC_CAPABILITIES_OPERATIONS.md)

扩展 manifest 声明执行方法和验证器；Skill 说明方法选择、科学限制和解释。Research State 记录要求和证据，新增执行入口无需向 State 添加方法专用分支。

## 准备与执行

用 `"$TSPI_PYTHON" -m tspi_runtime.executors --list` 查看已安装入口，选择 id/version 和安装目录 `etc/job.toml` 中的命名环境。声明提供后端键、固定脚本、纯 CLI 解析器、输入角色和输出。原生入口无需 Python 绑定；Python 入口使用目标环境配置的解释器。

准备命令写入请求并返回 `request_file` 与 `request_sha256`，连同 `node_id` 提交到 `job_start`。Runtime 检查文件和输入、执行 State 准入，并把 `prepared_ref`、Attempt 和提交意图一起登记。准备本身不产生 Attempt，也不证明科学结果。

任务临时 Python 方法用 `--script <文件.py> --backend <绑定>` 替代 executor/version，声明暂存依赖和收集输出。已登记证据通过 `--input-artifact <id或引用>` 传入，Runtime 核验实际暂存字节并保留来源。

丢失响应时复用原请求身份，通过 `job_status`、`job_reconcile` 和 `job_collect` 恢复；超时或客户端断连不代表允许重投。明确重复计算需要新身份和前驱、原因、预算声明。

## 环境与进程归属

job.toml 所选后端提供程序、Python 绑定、激活脚本及资源默认值。结构生成使用化学扩展的 `structure` 后端，化学验证器使用 `validation`；各目标须配置自己的依赖。执行入口与验证器可以声明 `requirements`，其中 `python` 和 `packages` 使用 Python 版本约束，`imports` 列出需要实际导入的模块；原生入口不声明 Python 依赖。

准备器在选定本地或 SSH 目标上核验解释器前缀、Conda 显式锁、pip 固定版本、安装回执、包清单，以及程序和激活文件摘要。请求身份包含这次观测；新提交时复查，真正运行时由暂存并固定摘要的检查程序再次复查。激活文件先检查再加载。变化导致拒绝执行，既有 Job 的查询和重试仍返回原身份。核验保证环境与记录一致，科学能力仍须由实际求解与验证证明。

安装回执增加 `inventory_sha256`。旧环境应通过 `scripts/install_job_environment.py --config … --environment … --backend … --adopt` 实际核验后发布新回执；不得手工补写摘要。安装器先检查配置结构，在受管控制环境和扩展安装后运行 `"$TSPI_PYTHON" -m tspi_runtime.environment_check --config "$TS_JOB_CONFIG"`，核验所有已配置入口，包括远端。`job_probe` 仍只表示平台可达。

应用提交的本地 Job 运行在独立 systemd 用户临时服务中，Host 重启不会连带终止它们。任务只接收最小环境和显式变量，资源请求通过 CPUQuota/MemoryMax 实施。Runtime 在 Job 内或配置的 scratch_root 下创建专属 scratch；显式环境值可引用 `{scratch}`。临时单元移除后，回执仍保留在工作区。

资源默认值只在准备或提交边界合并一次，顺序为目标、后端、显式请求；已准备入口的资源固定后不能在提交时覆盖。Attempt 和执行指纹记录实际资源。`allowed_queues` 仅是权限范围，不能代替 `submission.queue`。本地不接受队列字段；Torque 将 cpus/memory_mb 转为 nodes/ppn 和 mem，PBS 使用 select（不能同时声明 select 和 cpus/memory_mb）。walltime 与程序 timeout_seconds 同时存在时取较短值。

远端 Job 使用配置的 SSH/PBS 目标，与本地共享最小进程环境、线程默认值和 scratch 规则；不继承登录 shell 的科学环境，需要的路径和激活脚本必须由绑定明确提供。每个远端目录带本地 Job 路径的摘要，不同工作区的同名 Job 不共享目录。已接受任务通过保存的实际目录和 scheduler.id 恢复，旧目录只用于恢复原任务。

`command_timeout_seconds` 限制 SSH 控制命令（默认 60 秒），`transfer_timeout_seconds` 单独限制每次 rsync（默认 3600 秒），二者都不是科学程序的执行时限。回收排除本地 spec、receipt、status 等控制文件，计算输出不能覆盖它们。求解器结束和输出完整收集仍是两个独立事实。

远端提交明确关闭调度器自动邮件和自动重跑，通知与重复计算由研究流程管理。`qdel` 成功仅登记取消请求；查询到调度器终态或确认原记录已移除后才记录 cancelled。取消期间的连接故障仍为 unknown，程序先完成则保留实际退出结果。

## 证据与支持范围

Job 文件位于 `runs/jobs/<job_id>`。收集把声明文件登记为所属 Attempt 的 Artifact；显式 recursive 输出目录中的文件逐个保留来源。Finding 解释这些证据，要求检查及科学验证器判断其是否支持请求结果，退出码为零或报告已生成不足以证明成功。

随包执行入口覆盖 CF22D、xTB、Gaussian 输入、结构与图检查、映射 DA 候选、IRC 输入准备及 CF22D 就绪检查。Gaussian 显式输入入口也执行所支持的 TS/Freq/IRC 路由。CREST/QBICS 指导和 NEB 讨论不表示存在随包 runner；可使用已验证的安装程序或明确绑定的任务脚本，并说明实际覆盖范围。

## 验证

用 `tools/test/runner.py` 选择源码、Native 与发行检查。真实求解器和远端验收使用隔离工作区及明确绑定。合成 Gaussian 测试验证解析与证据关联，不能证明真实过渡态搜索一定收敛。
