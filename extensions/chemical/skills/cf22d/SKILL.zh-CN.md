---
name: cf22d
description: 规划、诊断并执行 PySCF CF22D 单结构的 SCF、优化、过渡态、频率和 RRHO 热化学计算。
---

# CF22D 计算

使用随 Skill 安装的 [scripts/run.py](scripts/run.py) 生成输入、执行程序并验证结果。先读取安装级 `job.toml` 中目标环境的 `pyscf` command、activation_script 和 environment；本地 `/home/iaw/soft` 与远程安装路径分别解析。

通过 [准备脚本](../method-selection/scripts/prepare_job.py) 生成通用 `job_start` 请求：

```text
python3 <method-selection>/scripts/prepare_job.py --config <job.toml> --environment <环境名> --backend pyscf --skill cf22d --xyz <结构.xyz> -- --task opt-sp
```

确认方法、基组、电荷、自旋和资源，补充 nodeId 与 timeoutSeconds 后提交返回的请求。脚本不会替 Agent 提交任务。它会暂存该 Skill 的 scripts 和 `_shared` 依赖，保留相对目录；不要只复制 run.py。激活发生在目标 Job 中，不需要 Provider 注册。

`run.py --help` 给出准确参数；`--task opt-sp` 明确执行优化，再以优化结构执行单点，任何步骤失败都会非零退出。`--spin` 是 2S（Gaussian 多重度为 spin+1）；XYZ 单位为 angstrom。选择新的空输出目录，不覆盖之前尝试。

声明 `results/result.json` 和 `results/geometry.xyz` 为 required 输出，并收集步骤目录的原始日志。结果记录实际方法、基组、输入与几何摘要、能量单位、收敛证据和脚本摘要。Job 退出 0 之外，还要检查 `validated=true` 及所需 steps；确认 opt 与 SP 的结构绑定。失败保留 result.json 和已有日志，不能用最后一个能量字符串替代完整验证。

通过 `job_status/job_collect/job_reconcile` 跟踪任务；使用返回的真实 attempt_id 保存等待点。科学 Finding 由 Agent 根据证据登记。Runtime 不判断化学方法，不允许静默换方法、基组或系统解释器。

本入口还支持 sp、opt、ts、freq、thermo、opt_freq、ts_freq；保留 CF22D/D3 可用性与优化收敛检查，缺失则失败。方法只允许 CF22D，不能用 RHF 替代。t006 使用 `--basis 6-31G**`。详细科学边界见 [工作流](references/cf22d_workflow.zh-CN.md)。

详细检查见 [environment_doctor.zh-CN](references/environment_doctor.zh-CN.md)。
