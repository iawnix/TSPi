# xTB 执行合同

已注册 xTB capability 为 `xtb.sp`、`xtb.opt`、`xtb.freq`、`xtb.opt_freq`、
`xtb.scan` 和 `xtb.md`。前四项要求一个 `xyz` 输入；scan 与 MD 准确要求一个 `xyz`
和一个 `control` 输入。

Adapter 接受 `gfn0`、`gfn1`、`gfn2` 或 `gfnff`；电荷与 `uhf` 显式提供。溶剂与
溶剂模型必须同时提供，模型为 `alpb` 或 `gbsa`。优化任务接受有界 `opt_level` 与
`max_cycles`。Capability descriptor 是准确机器合同；构造不熟悉请求前查询
`ts_state mode=capabilities`。

预期主要 Artifact 为：

| 任务 | 必需 Artifact |
| --- | --- |
| `sp` | `xtb.out` |
| `opt` | `xtbopt.xyz`、`xtb.out` |
| `freq` | `vibspectrum`、`xtb.out` |
| `opt_freq` | `xtbopt.xyz`、`vibspectrum`、`xtb.out` |
| `scan` | `xtbscan.log`、`xtbopt.xyz`、`xtb.out` |
| `md` | `xtb.trj`、`xtb.out` |

解析器报告执行、终止、适用时的 SCC 收敛、能量、几何、频率、scan point 和轨迹摘要。
这些是候选 Finding。检查负频位移以归属模式，并通过驻点优化和验证细化扫描极大值。
