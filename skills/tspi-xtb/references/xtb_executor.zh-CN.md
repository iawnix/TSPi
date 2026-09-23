# xTB 执行合同

已注册 xTB capability 为 `xtb.sp`、`xtb.opt`、`xtb.freq`、`xtb.opt_freq`、
`xtb.scan` 和 `xtb.md`。前四项要求一个 `xyz` 输入；scan 与 MD 准确要求一个 `xyz`
和一个 `control` 输入。

Adapter 接受 `gfn0`、`gfn1`、`gfn2` 或 `gfnff`；电荷与 `uhf` 显式提供。溶剂与
溶剂模型必须同时提供，模型为 `alpb` 或 `gbsa`。优化任务接受有界 `opt_level` 与
`max_cycles`。Capability descriptor 是准确机器合同；构造不熟悉请求前查询
`ts_state mode=capabilities`。

对于 `xtb.scan`，control Artifact 必须包含 `$scan` 段并以 `$end` 结束。`$constrain`
后也可以使用 `$end` 作为 block 分隔符。推荐的编号形式在 `$constrain` 中定义原子序号；每个 `$scan` 指令只引用约束的 1-based 序号，
并提供 `start`、`end`、`steps` 三个逗号分隔值：

```text
$constrain
  force constant=0.5
  distance: 5, 12, auto
$scan
  mode=sequential
  1: 1.5, 3.2, 18
$end
```

不要在编号式 `$scan` 行重复写 `5, 12`。关键字形式或拆开的 `start`/`end`/`steps`
字段不属于适配器合同；如果希望在扫描行直接定义约束，也支持原生 xTB 的命名内联形式：

```text
$scan
  distance: 5, 12, auto; 1.5, 3.2, 18
$end
```

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
