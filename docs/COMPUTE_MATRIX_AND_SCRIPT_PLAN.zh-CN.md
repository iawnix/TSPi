# 计算矩阵与脚本 Capability 规划

## 目标

方法比较必须先形成完整、可审计的任务矩阵，再进入 `compute_run` 生命周期。普通脚本也
通过同一生命周期执行，但脚本输出不能直接成为 ResearchMap 的科学结论。

## 方法矩阵

Chemical Extension 提供方法到 capability 的确定性路由：

| 方法 | Provider | 优化 | 单点 |
| --- | --- | --- | --- |
| CF22D/6-31G | PySCF | `pyscf.opt` | `pyscf.sp` |
| GFN2-xTB | xTB | `xtb.opt` | `xtb.sp` |
| M062X/6-31G | Gaussian | `gaussian` + `Opt` Route Section | `gaussian` + `SP` Route Section |

用户选择两个环境时，计划包含 `3 × 2 × 2 = 12` 个 Job。每个单点 Job 只能依赖同一方法、
同一环境的优化输出：

```text
method/environment/opt -> method/environment/sp
```

计划生成是纯操作，不创建 Attempt。计划结果至少包含 `job_id`、方法、capability、环境、
步骤、输入 Artifact 角色和 `depends_on`。Host 对每个 Job 查询精确的 catalog 和 readiness；
不可用的单元记录 `blocked`，其它独立单元继续执行。邮箱未配置只阻止 `notify_send`，不阻止
已就绪的计算。

已实现 `chemical.comparison.plan@1` Provider，输出
`chemical_computation_plan/1`。Agent 先调用该 Provider，再按依赖关系调用现有
`compute_run launch/inspect/finalize`。Gaussian 的方法和基组写入 `.gjf` Route Section，
例如 `# M062X/6-31G Opt` 与 `# M062X/6-31G SP`。

规划器位于 `extensions/chemical/providers/comparison_plan.py`，是无副作用的纯函数；它为
单点任务建立同方法、同环境的优化依赖，并在 readiness 映射中标记不可用单元。执行仍由
`compute_run` 负责，因此规划不会创建 Attempt 或写入 Research State。

## `script.bash@1`

已新增普通 `script` Extension 和 `script.bash@1` Compute capability。它不增加用户确认页面、
额外风险标签或新的权限配置；执行仍使用安装级默认环境和现有 Host 的 workspace 绑定、
超时、取消、崩溃处理及 JSONL Provider 协议。

请求通过 `compute_run launch` 进入生命周期，输入为不可变脚本 Artifact，参数使用数组，
不接受拼接后的任意 shell command 字符串：

```json
{
  "capability": "script.bash",
  "inputArtifacts": [{"inputRole": "script", "artifactId": "art_..."}],
  "parameters": {"args": ["--mode", "production"]},
  "execution": {"environment": "local"}
}
```

Provider 只收集预先声明的输出 manifest、stdout 和 stderr 诊断，并把脚本、参数摘要、
解释器、环境、输出 digest 和 parser 版本写入 provenance。脚本不能直接修改 ResearchMap，
也不能自行登记 Claim、Finding 或 Evidence；需要科学记录时由 Agent 读取结果后调用
`research_change`。

Provider 位于 `extensions/script/providers/`，由应用启动时注册到通用
`research_compute` capability registry。`script` backend 不要求在 `compute.toml` 中增加
专用命令绑定，默认使用 `/bin/bash`；脚本必须声明 `script_result.json`，其余输出通过
`output_manifest` 收集。

## 安装配置

`scripts/install_configured.py` 是统一的非交互安装入口，默认使用：

```text
安装目录: /home/iaw/ResearchAgent
配置目录: /home/iaw/DATA/tspi_install_config
工作区:   /home/iaw/ResearchAgent/workspaces
Web:      127.0.0.1:8766
收件人:   iawhaha@163.com
发件账户: 1558901061@qq.com
```

配置目录中的 `compute.toml`、`models.json`、`auth.json` 和 `smtp-password` 会被复制到安装
目录的私有状态；SMTP 使用 QQ preset，密码文件权限为 `0600`。Link Relay 默认使用
`https://tsphone.iawnix.xyz`；安装 Host 仍必须提供 Relay 管理员创建的一次性
`--link-enrollment-code`。如果只需要 Web 而暂时没有 enrollment code，可显式使用
`--phone-access disabled`。安装器会在写入配置前检查 enrollment code，避免生成半配置的
Link 状态。

## 验收

- t005 的 M062X 路由到 Gaussian，不再因为 PySCF 泛函列表而停止全部任务。
- 矩阵能生成 12 个 Job，并验证优化到单点的 Artifact 角色依赖。
- readiness 失败只阻塞对应矩阵单元及其无法满足输入依赖的下游单点单元，
  其它方法和环境继续执行。
- `script.bash@1` 经过 `compute_run`，产生 Attempt、Artifact 和 provenance。
- 脚本不能写入 canonical Research State。
- 无收件人时计算仍可完成，通知状态单独为 `user_input_required`。
- 统一安装器通过扩展发现、配置校验和安装器合同测试。
