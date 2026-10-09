# 准备科学 Job 请求

用 `"$TSPI_PYTHON" -m tspi_runtime.executors --list` 查看扩展声明的执行入口。每个入口声明后端、固定脚本、CLI 契约、输入角色和输出。准备命令为 `--config "$TS_JOB_CONFIG" --environment <环境> --executor <id> --version <版本> --input <角色>=<文件>`，`--` 后放 runner 参数。通用准备器仅暂存已声明资源并保留模块路径；目标 Python 来自 job.toml 的后端或环境绑定。

保留准备请求中的 request_id；同一次提交恢复时复用它，不因工具响应丢失而生成新 ID。明确重算时生成新请求。

执行显式 Gaussian 输入时，用 `--executor chemical.gaussian-input --version 1 --input input=<file>` 替代 `--input geometry=<file>`。
通过 `--dependency /absolute/source.chk=previous.chk` 暂存检查点或包含文件，
目标名称须匹配 `.gjf` 内的相对引用。用 `--collect results/ts.chk` 要求收集可供后续复用的检查点。
这些参数放在 `--` 前；`--validation saddle` 或 `--validation irc` 等 runner 参数
放在其后，不传 `--task`。输入格式、依赖文件内容、收集要求及脚本资源均参与请求身份计算。
helper 只封装当前计算，计算顺序由 Agent 决定，数值检查须结合 Gaussian Skill 作科学解释。

选择方法或准备已指定方法的执行时都使用本 Skill。从列出的路径读取具体方法 Skill。读取安装配置、检查方法可用性属于 Agent 的工作，尚未验证不应自动变成用户输入门槛。

Python 依赖由安装阶段创建的 Conda 环境隔离，并通过 job.toml 的结构化 python 绑定选择：backend.python 优先，否则继承 environment.python。用 "$TSPI_PYTHON" 执行本地准备 helper；远程 runner 使用配置的 Conda prefix，不猜 python3、不用 --python 覆盖。CF22D 使用 backends.pyscf.python，不再同时指定 Python command。缺失环境交由安装维护处理，不在研究回合临时 pip install。


在 `--` 前传 `--output <workspace>/prepared/<cell>.json` 保存完整请求。脚本输出
request_file/request_sha256，直接交给 job_start，只补 node_id 和可选 timeout_seconds；
不要手抄 command/inputs。相同输入与配置保留 work_id/request_id，主动重新计算才用
--work-id 指定新身份。修改请求文件后必须重新核对并计算摘要。

任务临时 Python 方法使用 `--script <文件.py> --backend <绑定>` 替代 executor/version，
通过 `--dependency <源>=<目标>` 暂存依赖、`--collect <相对输出>` 声明结果。
脚本和依赖会固定摘要并在所选 Python 绑定内执行。已登记输入用
`--input-artifact <id或引用>`；Runtime 核对其真实字节已暂存，并把来源关联到收集结果。

远程 job.toml 的 environment 或 backend 必须明确配置 submission.queue；
submission.resources 保存 CPU、内存、walltime，backend 覆盖环境默认值。
allowed_queues 不负责选择队列。缺配置交由安装维护，不猜队列。可用
submission.queue_wait_seconds 设置一次性排队超时诊断事件；收到后查看
job_status.diagnostics。Q/R 尚无退出回执是正常现象；重投或改队列前先对账原 Job。

准备脚本在写入请求前，使用所选 runner 共用的纯 CLI 解析器校验透传参数；未知参数和覆盖受管输入/输出/可执行程序路径会被拒绝。xTB runner 固定为 GFN2-xTB，不要追加 --method。准备过程检查声明的参数和目标依赖；方法能否处理指定输入仍需通过实际科学 Job 验证。
