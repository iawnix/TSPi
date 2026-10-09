# xTB 执行与解释

## 选择执行方式

`chemical.xtb@1` 是单点/优化的便捷封装，固定 GFN2-xTB；其 `--task` 为 `sp`、`opt`、`opt-sp`。
更广的原生功能通过通用 `job_start` 的 command 参数运行，或编写任务脚本后使用
准备器的 `--script` 路径。二者均不要求新增 `execution.json` 登记。
遵循[Job 契约](../../method-selection/references/backend_contract.zh-CN.md)，明确目标平台、
程序路径/激活环境、输入文件、资源与输出。先检查目标上已安装版本的帮助，不能假定远端与本机版本一致。

下表是原生 xTB 命令示例，假设输入为 `input.xyz`、中性单重态，程序名已解析到目标环境。
实际运行应放在 Job 工作目录中，捕获 stdout/stderr 为 `xtb.out`；修改 `--chrg`、`--uhf` 等设置以匹配体系。

| 任务 | 原生命令示例 | 收集的主要材料 |
| --- | --- | --- |
| 单点 | `xtb input.xyz --gfn 2 --sp --chrg 0 --uhf 0` | `xtb.out` |
| 优化 | `xtb input.xyz --gfn 2 --opt tight --chrg 0 --uhf 0` | `xtbopt.xyz`、`xtb.out` |
| 频率/Hessian | `xtb input.xyz --gfn 2 --hess --chrg 0 --uhf 0` | `vibspectrum`、`hessian`、`xtb.out`，以及可用的模式位移文件 |
| 优化后频率 | `xtb input.xyz --gfn 2 --ohess --chrg 0 --uhf 0` | `xtbopt.xyz`、`vibspectrum`、`hessian`、`xtb.out` |
| 约束扫描 | `xtb input.xyz --gfn 2 --opt tight --input scan.inp --chrg 0 --uhf 0` | `scan.inp`、`xtbscan.log`、`xtbopt.xyz`、`xtb.out` |
| 分子动力学 | `xtb input.xyz --gfn 2 --md --input md.inp --chrg 0 --uhf 0` | `md.inp`、`xtb.trj`、`xtb.out`及可用的能量/温度记录 |

## 频率

`--hess` 对给定几何计算 Hessian，`--ohess` 先优化再计算。极小点的振动判断需要驻点依据；
保留频率表、几何和模式位移。负频数不能代替模式归属，低频噪声和收敛阈值需要单独解释。

## 约束扫描

在 `scan.inp` 中声明扫描坐标。下例只是距离扫描示例，原子序号从 1 开始，需按实际体系修改：

```text
$constrain
  force constant=0.5
  distance: 5, 12, auto
$scan
  mode=sequential
  1: 1.5, 3.2, 18
$end
```

`1:` 引用第一条约束；同一行给出起点、终点与步数，不要再次填写原子序号。
也可使用原生内联写法 `distance: 5, 12, auto; 1.5, 3.2, 18`。
逐点记录目标与实际坐标、能量及收敛情况，保留扫描方向和失败点；扫描最高点只是进一步寻找鞍点的候选。

## 分子动力学

在 `md.inp` 的 `$md` 块中显式设定温度、总时长、时间步长和轨迹输出间隔等参数，
按目标版本核对单位与恒温设置。记录初始几何、速度/随机种子（程序支持时）及约束。
检查轨迹、温度、能量漂移和积分稳定性；非平衡轨迹本身不能给出平衡自由能或证明反应机理。

## 解析范围

`scripts/parser.py::parse_xtb_artifacts` 接受 `sp`、`opt`、`freq`、`opt_freq`、`md`，
可提取 SCC、能量、优化、频率及轨迹摘要。通用 Job 不会自动调用它；需要在分析脚本中显式导入，
并保留其 `_shared/xyz.py` 依赖。
扫描没有对应的解析分支，应分析 `xtbscan.log` 的各帧与原始日志，并登记实际分析产物。
解析字段是观察数据，科学结论仍需结合原始输出与任务判据。
