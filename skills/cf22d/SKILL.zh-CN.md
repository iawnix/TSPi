---
name: cf22d
description: 为已注册的 PySCF CF22D 单结构工作流规划、诊断并执行 SCF、优化、过渡态、频率和 RRHO 热化学任务。
---

# TSPi CF22D

[English version](SKILL.md)

使用本 Skill 处理密度泛函方法为 CF22D 的、有边界的 PySCF 工作流。独立的
`pyscf_runner` 只是输入与执行辅助包；只有 TSPi 暴露了确定性的 capability、输入
role、输出 role、解析合同和任务验证测试后，它才是 TSPi Backend。

执行前读取 Artifact catalog 和实时 compute catalog：

```text
research_read mode=artifacts
research_read mode=capabilities capabilityKind=compute
```

只使用 catalog 返回的准确 capability 和参数 schema。若没有注册 PySCF/CF22D capability，
只能给出方法建议和 doctor 计划。不得虚构 capability 名称、为不可用 descriptor 构造
`compute_run` 请求、通过任意 shell 调用 `pyscf-runner`，或把本地 smoke test 说成 TSPi 计算。

当前 adapter 在实时 catalog 中出现时使用版本 1 的 ID：`pyscf.sp`、`pyscf.opt`、
`pyscf.ts`、`pyscf.freq`、`pyscf.thermo`、`pyscf.opt_freq` 和 `pyscf.ts_freq`。这只是
路由提示，不能代替 catalog 发现或就绪检查。

在不可变 calculation intent 中绑定源 XYZ Artifact、任务列表、电荷、PySCF spin
（`2S`，不是多重度）、基组、CF22D 方法设置、优化/TS 设置、频率阈值、热化学条件、
运行资源和输出策略。首次运行以及依赖、配置或环境变化后，运行只读环境 doctor。任务
远端目标使用 `TSPi --check-remote`；本地目标使用安装级或 adapter 暴露的 runtime probe。
任务顺序、输入/输出记录和科学检查见
[cf22d_workflow.zh-CN.md](references/cf22d_workflow.zh-CN.md)；本地与远端就绪检查见
[environment_doctor.zh-CN.md](references/environment_doctor.zh-CN.md)。

PySCF Backend 必须在 `compute.toml` 中绑定由运维管理的专用解释器，该环境应包含
PySCF、geomeTRIC、`pyscf-dispersion` 和 TSPi runner 模块。本地 worker 会先加载配置的
activation script；远程 Torque 作业在只暂存输入 basename 后加载远程 activation script。
绑定缺失或过期时应在 preflight 阶段失败；不得在计算任务内安装依赖，也不得回退到宿主
Python。

不得静默替换其他 `xc` 泛函。若 descriptor 允许覆盖 `xc`，只有冻结 intent 明确记录
`CF22D` 时才使用本 Skill；其他泛函应交给方法选择和适用的执行 Skill。

源 Runner 负责单结构的 `sp`、`opt`、`ts`、`freq` 和 `thermo`。TSPi adapter 还可能暴露
组合的 `opt_freq` 和 `ts_freq` capability；实际请求以 descriptor 和 Artifact manifest
为准。`opt` 与 `ts` 互斥；`freq` 会隐式增加 SCF，`thermo` 会隐式增加 SCF 和频率。TS 加热化学的顺序是
`ts -> sp -> freq -> 驻点频率计数 -> thermo`。它不会执行 IRC、NEB、反应扫描、端点优化
或交叉点搜索。

正常终止、SCF 收敛和一个虚频是不同事实。Runner 的驻点检查只统计显著虚频（默认阈值
`-20 cm^-1`），不会检查振动模式向量，也不能建立端点身份。这些问题交给
`tspi-ts-validation`、`tspi-irc` 和 `tspi-mechanism-reasoning`；能量与 RRHO 解释交给
`tspi-energetics`。

将 adapter 的 `memory_mb`（源 Runner 称为 `max_memory_mb`）视为 PySCF 预算，而不是操作系统硬限制。配置的 scratch 基目录只能
包含 Runner 自己创建的运行子目录；清理时不得删除基目录或无关文件。核对 capability
声明的主要输出后，再通过 Research Kernel 分别记录 FactFinding 或 IssueFinding。独立
Runner 通常写出 `run.log`、`result.json`、任务记录、几何、Hessian/频率和热化学文件；
TSPi adapter 也可能声明 `pyscf.out`、`pyscf_result.json` 和 `pyscf_*` JSON/XYZ
Artifact。实时 capability 的 Artifact manifest 才是权威，不要根据本文件猜文件名。解析
失败或结果不完整不是化学结论。
