---
name: cf22d
description: 执行并解释 PySCF CF22D 单点、结构优化、过渡态、频率和 RRHO 热化学校正。
---

# CF22D 计算

通过 `chemical.cf22d@1` 使用目标的 `pyscf` 绑定，支持 `sp`、`opt`、
`opt-sp`、`ts`、`freq`、`thermo`、`opt_freq` 和 `ts_freq`。目标环境必须
实际具备 CF22D 及其色散实现。

```bash
"$CORAGENT_PYTHON" -m research_agent.application.executors --config "$CORAGENT_JOB_CONFIG" --environment local --executor chemical.cf22d --version 1 --input geometry=input.xyz --output prepared/cf22d.json -- --task opt-sp --basis def2-tzvp --charge 0 --multiplicity 1
```

将返回的请求文件和摘要连同对应 node_id 交给 `job_start`。准备器负责暂存声明的
脚本和输出。结果字段、单位、多重度及优化到单点的关系见
[共享 runner 契约](../method-selection/references/runner_results.zh-CN.md)。

根据用户问题选择基组与资源，默认基组为 `def2-tzvp`。解释驻点和自由能前，
检查 SCF、优化收敛、振动模式及 RRHO 的适用范围。TS 优化本身不能证明目标
反应关系。

- [科学检查与方法边界](references/cf22d_workflow.zh-CN.md)
- [目标环境诊断](references/environment_doctor.zh-CN.md)
