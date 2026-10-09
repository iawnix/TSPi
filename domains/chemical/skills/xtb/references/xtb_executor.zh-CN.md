# xTB 执行与原生产物检查

内置 `scripts/run.py` 和准备 helper 支持 GFN2-xTB 的 `opt`、`sp`、`opt-sp`，
实际参数以其 `--help` 为准。额外的原生 xTB 任务可在核实所安装程序的参数、输入和必需
输出后，通过通用 Job Runtime 执行。现有解析函数是分析 helper，不是自动调用的 workflow adapter。

下列扫描语法与输出清单属于科学/原生程序参考，不会为内置 runner 增加 freq、scan 或 md 选项。

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
这些是候选研究记录。检查负频位移以归属模式，并通过驻点优化和验证细化扫描极大值。
