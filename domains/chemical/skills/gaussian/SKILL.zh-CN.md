---
name: gaussian
description: 准备、执行并检查 Gaussian 单点、优化、频率、过渡态、IRC、QST 和显式扫描输入。
---

# Gaussian 计算

XYZ 的 `sp`、`opt`、`opt-sp` 使用 `chemical.gaussian@1`，默认采用
M062X/6-31G**、Opt=Tight 或 SP、SCF=Tight、Int=UltraFine。完整显式
输入使用 `chemical.gaussian-input@1`，两者都采用目标的 `gaussian` 绑定。

```bash
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.gaussian --version 1 --input geometry=input.xyz --output prepared/gaussian.json -- --task opt-sp --charge 0 --multiplicity 1
```

将返回的请求文件和摘要连同对应 node_id 交给 `job_start`。输出和电子态语义见
[共享 runner 契约](../method-selection/references/runner_results.zh-CN.md)。
检查 route 回读、正常终止和收敛。缺少频率证据的优化结构不能确认为极小值。

## 显式 Gaussian 输入

为 TS/Freq/IRC/QST/scan 准备完整 .gjf。每个 Link1 段必须匹配请求的
`--method`、`--basis`、`--threads`、`--memory-mb`、`--charge` 和
`--multiplicity`。Geom=AllCheck 的电子态需要通过 checkpoint 证据核对。
用 `--dependency /absolute/source.chk=previous.chk` 暂存依赖，输入文件中
只引用相对暂存路径，并收集后续计算需要的 checkpoint。

```bash
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.gaussian-input --version 1 --input input=ts.gjf --collect results/ts.chk --output prepared/ts.json -- --method M062X --basis '6-31G**' --charge 0 --multiplicity 1 --threads 12 --memory-mb 4000 --validation saddle
```

`--validation opt/sp/frequency/minimum/saddle/irc/none` 选择 runner 检查。
`saddle` 检查驻点收敛和一个虚频；还需检查模式方向，并使用注册的鞍点验证器
核对指定转化。IRC 输出路径与端点材料，端点归属通过连通性验证器及关联证据
确认。显式扫描输入可以执行，当前没有专门验证扫描完整性的内置验证器。

详见 [Gaussian 科学验证](references/gaussian_validation.zh-CN.md)。
