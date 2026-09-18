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

## 运行时就绪条件

远程 `ase_neb` 软件 profile 必须选择由运维人员管理的版本化环境中的 Python
解释器。该解释器必须能导入 ASE、NumPy，以及与准备计算的 TSPi 版本一致的
`ts_agent.backends.ase_neb_runner`。在 profile 环境中将 `TS_ASE_NEB_XTB`
设为已验证的 xTB 可执行文件，不依赖交互式 shell 的 `PATH`。

部署或修改 profile 后、首次提交 NEB 前运行 `TSPi --check-remote`。解释器缺失、
导入失败、runner 版本不一致或 xTB 探测失败都属于运维失败，不能作为反应路径
证据。不得从计算作业中安装包，也不得把软件安装到研究工作区。按照
[ASE NEB 部署流程](../../../docs/INSTALLATION.md#deploy-the-ase-neb-runtime-with-pixi)
操作，并且只有登录节点和计算节点冒烟检查都通过后才能切换软件 profile。
