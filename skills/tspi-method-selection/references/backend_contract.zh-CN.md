# Backend 合同

Backend 是确定性适配器。它描述支持的程序任务、校验参数、准备不可变输入/脚本、声明
预期 Artifact，并解析本地输出。Root 选择方法并解释已核验结果。

使用 `ts_state mode=capabilities capabilityKind=compute` 获取当前机器可读目录；公共
调用见 [compute_tools.zh-CN.md](../../tspi-orchestration/references/compute_tools.zh-CN.md)。

## 支持的任务

- Gaussian：`sp`、`opt`、`ts`、`freq`、`opt_freq`、`irc`。
- xTB：`sp`、`opt`、`freq`、`opt_freq`、`scan`、`md`。
- CREST：`conformer_search`。
- 使用 xTB CLI calculator 的 ASE：`neb`。

QBICS DMECP 当前不是已注册 capability。Backend 只有具备确定性解析合同与任务验证测试后
才成为公共能力；只有输入准备器并不充分。

使用目录构造 `ts_calc` 请求。选择 `executionTarget.kind = "local"` 或 `"remote"`；
安装共享 `compute.toml` 后，还要选择相应环境名。两者使用相同生命周期和结果合同。远端
就绪状态在计算 preflight 中检查，不是独立计算 API。

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

执行边界并非远端专用：本地目标在 `dry_run=true` 时支持确定性准备，在 `dry_run=false`
时启动有边界、持久化的 Attempt 本地 worker。远端目标仅在 `dry_run=false` 时使用配置的
远端环境；远端 dry-run 只生成并校验提交计划，不联系调度器。Launch 前检查所选环境和
Backend 绑定。

## 记录科学结果

Root 对照主要 Artifact 核验解析输出，拆分 Finding statement，并应用 `ts_change`。机理、
端点身份、振动模式归属和 Claim 状态由相关方法 Skill 评估；需要可见 verdict 时使用 Gate
criteria。
