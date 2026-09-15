# ASE NEB 执行器

已注册能力为 `ase.neb@1`，它只接受一个 `reactant` 和一个 `product` XYZ
artifact。每个端点必须只有一帧，两个文件的原子及其顺序必须相同。若端点坐标
完全相同，后端会在准备阶段拒绝请求。

ASE 负责 NEB 插值和 FIRE 优化，固定的 xTB CLI calculator 为每个 image 提供
能量和笛卡尔梯度。支持的电子结构方法为 `gfn1` 和 `gfn2`，不会隐式替换
calculator。参数类型与边界以能力目录为准，主要参数包括 `images`、`fmax`、
`max_steps`、`spring_constant`、`interpolation`、`climb`、
`remove_rotation_and_translation`、`method`、`charge`、`uhf`、`accuracy`、
`electronic_temperature`、`solvent_model` 和 `solvent`。

必需产物为：

- `ase_neb.out`：优化日志和运行器完成标记；
- `neb.traj`：ASE 可读取的最终 image 路径；
- `neb_path.xyz`：包含每个 image 能量的可移植最终路径；
- `neb_summary.json`：带版本的运行事实和收敛指标。

解析器会交叉校验摘要、可移植路径、绑定端点、能量列表、image 数、原子数和
全部必需文件。Python 进程正常结束与任务完成是两个独立状态。即使程序正常
结束，只要 `converged=false`、最大 NEB 力高于 `fmax`、端点不匹配或路径数据
不完整，`task_validation.status` 仍为 `incomplete`。

远程 `ase_neb` 软件 profile 必须选择一个能导入 ASE、NumPy 和对应版本
`ts_agent.backends.ase_neb_runner` 的 Python 环境。若 `xtb` 不在 `PATH`，
应在 profile 环境中设置 `TS_ASE_NEB_XTB`。提交前运行 `ts_remote doctor`。
