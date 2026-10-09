---
name: xtb
description: 执行 GFN2-xTB 单点和结构优化，用于低成本结构筛选。
---

# GFN2-xTB 计算

`chemical.xtb@1` 使用配置的 `xtb` 程序及包装脚本环境，支持 `sp`、`opt`
和 `opt-sp`。

```bash
"$TSPI_PYTHON" -m tspi_runtime.executors --config "$TS_JOB_CONFIG" --environment local --executor chemical.xtb --version 1 --input geometry=input.xyz --output prepared/xtb.json -- --task opt-sp --charge 0 --multiplicity 1
```

将返回的请求文件和摘要连同对应 Node 交给 `job_start`。输出和电子态语义见
[共享 runner 契约](../method-selection/references/runner_results.zh-CN.md)。
多重度由 runner 转成 xTB 的未配对电子参数。

检查 SCC、优化收敛以及目标分子结构是否保留。只能在一致方法和电子态下比较
能量；不能用与 DFT 的绝对能量差判断准确度。当前执行入口未实现频率、扫描
或分子动力学任务。

详见 [xTB 执行与解释](references/xtb_executor.zh-CN.md)。
