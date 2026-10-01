# Backend 合同

Backend 是确定性适配器。它描述支持的程序任务、校验参数、准备不可变输入/脚本、声明
预期 Artifact，并解析本地输出。Root 选择方法并解释已核验结果。

使用 `research_read mode=capabilities capabilityKind=compute` 获取当前机器可读目录；公共
调用见 [compute_tools.zh-CN.md](../../tspi-orchestration/references/compute_tools.zh-CN.md)。

## 支持的任务

- Gaussian：已注册的 `gaussian@1` 执行器。`.gjf` 输入的 Route Section 决定
  `sp`、`opt`、`ts`、`freq`、`opt_freq`、`irc`、scan、QST 等 Gaussian 模式。
- xTB：`sp`、`opt`、`freq`、`opt_freq`、`scan`、`md`。
- CREST：`conformer_search`。
- ASE NEB：已注册的 `ase.neb@1`，默认使用 xTB CLI calculator；需要 Gaussian 逐 image
  力时显式设置 `calculator=gaussian_cli`。

QBICS DMECP 当前不是已注册 capability。Backend 只有具备确定性解析合同与任务验证测试后
才成为公共能力；只有输入准备器并不充分。

使用目录构造 `compute_run` 请求。选择 `executionTarget.kind = "local"` 或 `"remote"`；
安装共享 `compute.toml` 后，还要选择相应环境名。两者使用相同生命周期和结果合同。远端
Native `compute_readiness` 执行与计算 preflight 相同的只读环境检查；它不会创建 intent 或提交任务。

实时目录是 capability identity 与 version 的权威来源。Skill 文字、Backend descriptor、已安装
可执行文件或目录列表都不会注册 capability，也不能证明其可运行。先查询精确的
`capability_id@version`，再使用该 capability、选定的 `environment_id` 和 `execution_kind`
调用 `compute_readiness`。readiness 为 `unknown` 或 `deferred` 不等于可执行健康；真实启动前还要
使用环境 doctor 或 `TSPi --check-remote doctor`。

Local/remote 是独立于 capability identity 的执行环境属性。远端请求必须使用 Native
`compute_run` 的 `operation=launch` 与 `executionTarget`；通用 capability invocation 形式不能
携带 remote selector，也不能创建绑定调度器的 intent。两种目标使用相同生命周期和不可变 intent。

例如，本地请求可绑定 `{"kind":"local","environment":"local"}`；同一 capability
也可绑定 `{"kind":"remote","environment":"cluster_1w",...}`。

## Adapter 输出

准备阶段必须声明准确的生成文件、命令、预期 Artifact、Backend 绑定、Compute 环境和解析
合同，且不能接受任意 shell。Parse 必须报告结构化程序事实与来源，同时保留缺失、歧义和
失败状态。

解析器输出属于 Backend 所有的事实，不决定所请求任务是否成功。Compute 层在
`program_status` 记录程序终止，并在 `task_validation` 中单独评估 capability 特定的完成
情况。两者都不是科学 verdict；Gaussian 单点、优化、过渡态优化和频率任务不会仅因使用
Gaussian 解析器就继承科学上的过渡态评估规则。

Host 将每次 launch 冻结为 `ts-calculation-intent/7`，包括 Node 与科学 intent 摘要以及
同一 Node 内的 Attempt lineage。方法、输入、影响命令的参数或预期输出发生任何变化，都
需要新的 recalculation intent。

执行边界对本地和远端目标使用同一合同。公共 launch 合同没有 `dry_run` 字段：Launch 会
校验所选环境和 Backend 绑定，然后执行一个有边界的 Attempt 生命周期。只需要准备或检查
环境健康时，使用 `compute_readiness` 和 Host preflight 诊断；这些检查不会创建
Calculation Attempt。

## 记录科学结果

Root 对照主要 Artifact 核验解析输出，拆分 Finding statement，并应用 `research_change`。机理、
端点身份、振动模式归属和 Claim 状态由相关方法 Skill 评估；需要可见 verdict 时使用 Gate
criteria。
