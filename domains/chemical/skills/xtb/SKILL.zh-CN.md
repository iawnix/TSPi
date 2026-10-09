---
name: xtb
description: 使用 xTB 进行低成本结构筛选、单点、优化、频率、约束扫描和分子动力学，并分析原始输出。
---

# xTB 计算

根据任务选择单点、结构优化、频率、约束扫描或分子动力学，明确方法、电荷、电子态和溶剂设置。

单点与优化可以使用 `chemical.xtb@1`，它固定使用 GFN2-xTB，接受 `sp`、`opt`、`opt-sp`：

```bash
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.xtb --version 1 --input geometry=input.xyz --output prepared/xtb.json -- --task opt-sp --charge 0 --multiplicity 1
```

将返回的请求文件和摘要交给 `job_start`，需要关联研究问题时提供 node_id。
输出和电子态语义见[共享 runner 契约](../method-selection/references/runner_results.zh-CN.md)。
该封装把多重度转换为 xTB 的未配对电子参数。

频率、扫描和动力学通过通用 Job 运行原生 xTB 命令，准备控制文件并声明要收集的输出。
不需要先把任务注册为 executor，也不要把原生命令选项传给上述封装的 `--task`。
具体命令、输入和解析范围见 [xTB 执行与解释](references/xtb_executor.zh-CN.md)。

检查 SCC（适用时）、优化收敛和结构身份；频率检查振动模式，扫描检查约束与每点收敛，
动力学检查积分稳定性与轨迹。能量比较需要一致的方法、电子态和能量定义；
不能用 xTB 与 DFT 的绝对能量差判断准确度。
