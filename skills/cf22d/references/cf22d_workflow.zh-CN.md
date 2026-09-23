# CF22D 工作流

本参考描述源 Runner 的合同，不创建 TSPi capability，也不授权直接启动进程。

## 内容

- [输入合同](#输入合同)
- [任务图](#任务图)
- [输出与核验](#输出与核验)
- [科学边界](#科学边界)

## 输入合同

源 Runner 通过 `pyscf-runner input.yaml` 或
`python -m pyscf_runner input.yaml` 接受 YAML/JSON。Python API 为：

```python
from pyscf_runner import PySCFRunner, WorkflowConfig

result = PySCFRunner(config).run(["sp", "freq"])
```

必需的 molecule 字段是 `molecule.xyz_file`。即使使用默认值，也要在 intent 中保留以下
字段：

- `molecule`：XYZ 路径、`basis`（默认 `def2-tzvp`）、`charge`、作为 PySCF `2S` 的
  `spin`、`unit` 和 verbosity；
- `method`：`xc: CF22D`、网格等级（默认 `6`）、SCF `conv_tol`（默认 `1e-10`）、
  最大循环次数（默认 `400`）和可选 checkpoint；
- `optimization` 或 `ts`：收敛阈值、最大步数以及是否使用初始 Hessian；
- `frequency`：normal mode 输出和 `imaginary_threshold_cm`（默认 `-20.0`）；
- `thermo`：RRHO 校正使用的温度和压力；
- `runtime`：源配置的 `max_memory_mb`（TSPi descriptor 称为 `memory_mb`）、`num_threads`、
  scratch 策略、额外环境变量、资源记录和
  `raise_on_error`；
- `output`：结果目录/前缀、覆盖策略、快照、checkpoint、Hessian、频率和热化学文件。

以上是独立 Runner 的默认值。TSPi adapter 可以有意选择其他有边界默认值（例如更低的网格
等级或更少的 SCF 循环）；应以实时 capability descriptor 和冻结的 calculation intent 为
权威，并记录实际生效值。

当前 adapter 保持源项目的默认行为：`ts` 和 `ts_freq` 默认启用初始 Hessian；intent
可以显式关闭它。

修复输入时不得静默改变电荷、自旋、基组、方法或任务顺序。科学绑定改变后必须创建新的
calculation intent；若仍回答同一 Node 问题，还应显式标记为 recalculation。

## 任务图

独立 Runner 支持 `sp`、`opt`、`ts`、`freq` 和 `thermo`。当前 TSPi adapter 将这些任务
映射到版本 1 的 capability ID `pyscf.sp`、`pyscf.opt`、`pyscf.ts`、`pyscf.freq` 和
`pyscf.thermo`，并额外提供组合 descriptor `pyscf.opt_freq` 和 `pyscf.ts_freq`。应使用
实时 catalog 的版本和 schema；不要把源 YAML 任务列表当成 `ts_calc` capability 名称。

- `opt` 与 `ts` 不能同时请求；
- `freq` 需要当前几何上的 SCF；未请求 `sp` 时，SCF 会隐式执行；
- `thermo` 同时需要 SCF 与频率；未请求时两者会隐式执行；
- `ts` 先改变几何，再进行下游 SCF/频率；TS 加热化学的组合顺序是
  `TS -> SP -> FREQ -> TS 验证 -> THERMO`；
- 单独的 `thermo` 不会优化极小值或过渡态。
- `opt_freq` 和 `ts_freq` 在一个 adapter 任务中组合几何与频率工作，但不会增加 IRC 或端点
  证据。

Runner 会分开记录显式任务和隐式任务。总结来源时要保持二者可区分。

## 输出与核验

独立 Runner 的成功或失败运行都应保留运行目录，其中包括日志、解析后的配置、原始输入
快照、顶层 JSON 结果、任务 JSON 记录，以及按配置启用的 checkpoint、优化/TS 几何、
Hessian、频率和热化学文件。TSPi adapter 也可能把结果暴露为已声明的
`pyscf.out`、`pyscf_result.json`、`pyscf_geometry.xyz`、`pyscf_frequencies.json`、
`pyscf_hessian.npy` 和 `pyscf_thermo.json`；实时 capability descriptor 与 Artifact
manifest 才是权威，不要从本 reference 猜文件名。资源记录可以包括请求线程数、实际 PySCF
线程数、内存预算、墙钟/CPU 时间和 RSS 快照。RSS 是进程快照，不是任务独占峰值。

当前 adapter descriptor 使用 `pyscf.output/1` 解析合同；仍应核对实时 catalog 返回的
parser 值并把它绑定到 calculation intent。仅有 parser 名称不能证明必需 Artifact 或任务
验证事实已经存在。

按以下顺序核验：

1. 输出属于绑定的输入 digest 和 calculation intent；
2. 程序到达预期终点，且存在 SCF 收敛证据；
3. 必需任务输出存在且内部一致；
4. 将 Runner 的 task validation 作为运行证据读取，不把它当作机理 Claim。

`raise_on_error: false` 时，失败任务仍保留在任务 JSON 和 `result.json` 中。保留错误类、
消息以及可用的 traceback；不要把它们替换为空结果，也不要用改变后的参数重试。

## 科学边界

内置 TS 验证只统计低于配置阈值的频率：极小值候选应为零，一阶鞍点候选应恰好一个。
它不验证虚频位移、原子映射、立体化学、端点盆地或 IRC，也不能证明 CF22D 适用于多参考、
自旋交叉、金属或强关联问题。

工作流是单结构的。IRC、NEB、反应扫描、端点身份、交叉点/DMECP 搜索、构象集合、同位素
校正和微观动力学不属于该 Runner。应使用相应 TSPi Skill 和实时注册 capability，不要
隐式扩展 CF22D 结果。
