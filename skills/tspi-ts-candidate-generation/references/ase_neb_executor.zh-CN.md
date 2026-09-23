# ASE NEB 执行器

已注册能力为 `ase.neb@1`，它只接受一个 `reactant` 和一个 `product` XYZ
artifact。每个端点必须只有一帧，两个文件的原子及其顺序必须相同。若端点坐标
没有实际构型变化（包括仅整体平移或旋转），后端会在准备阶段拒绝请求。

ASE 负责 NEB 插值和路径优化，固定的 xTB CLI calculator 为每个 image 提供
能量和笛卡尔梯度。支持的电子结构方法为 `gfn1` 和 `gfn2`，不会隐式替换
calculator。托管 runner 对 image 串行计算且不启用 ASE 预条件器；并行 image
执行和 `precon` 暂不属于此能力。参数类型与边界以能力目录为准，主要参数包括 `images`、`fmax`、
`max_steps`、`spring_constant`、`interpolation`、`neb_method`、`optimizer`、
`climb`、`ci_neb`、`ci_fmax`、`remove_rotation_and_translation`、`method`、
`charge`、`uhf`、`accuracy`、`electronic_temperature`、`solvent_model` 和
`solvent`。

`neb_method` 可选 `aseneb`、`improvedtangent`、`eb`、`spline` 和 `string`；
`optimizer` 可选 `FIRE`、`BFGS`、`LBFGS` 和 `MDMin`。默认值会显式写入准备命令，
并回显到 `neb_summary.json`，不会依赖 ASE 版本的隐式默认值。

端点是 intent 绑定的输入结构；`ase.neb@1` 不会自动预优化端点。需要松弛端点时，
先使用已注册的优化能力生成新的 XYZ artifact，再把这两个 artifact 绑定到新的 NEB
intent。当前能力也不接受 `transition_state` 输入，不会自动寻找或生成 TS；TS 引导
插值必须先有独立的 TS 候选，并由后续版本显式扩展输入角色后才能使用。

`ci_neb` 默认关闭。启用后先以 `climb=false` 收敛普通 NEB，再以 climbing
image 和 `ci_fmax`（未提供时回退到 `fmax`）启动第二个阶段；普通 NEB 未收敛
时不会进入 CI 阶段。summary 会回显实际 settings，并在 `stages` 和 `history`
中记录各阶段的收敛状态及有界的逐步过程数据；这些字段是向后兼容的附加字段。
`ci_fmax` 仅在 `ci_neb=true` 时有效；普通 NEB 和旧式单阶段 `climb` 不执行 CI 阶段，
因此会将该字段回显为 `null`。
旧式单阶段 `climb` 与 `ci_neb` 互斥，intent 必须明确选择其中一种模式。
history 记录各 image 的能量和最大 NEB 力，不包含逐步坐标；`neb.traj` 和
`neb_path.xyz` 仅保存最终路径。

必需产物为：

- `ase_neb.out`：由计算 worker 捕获标准输出形成的优化日志和运行器完成标记；
- `neb.traj`：ASE 可读取的最终 image 路径；
- `neb_path.xyz`：包含每个 image 能量的可移植最终路径；
- `neb_summary.json`：带版本的运行事实和收敛指标。

能力暴露的逻辑输出角色为 `program_output`、`reaction_path`、`trajectory` 和
`run_summary`；有界过程记录包含在 `neb_summary.json` 中，不另行产生不受控的日志
Artifact。

解析器会交叉校验摘要、可移植路径、绑定端点、能量列表、image 数、原子数和
全部必需文件。Python 进程正常结束与任务完成是两个独立状态。即使程序正常
结束，只要 `converged=false`、最大 NEB 力高于最终阶段的 `fmax`（或 `ci_fmax`）、
端点不匹配或路径数据
不完整，`task_validation.status` 仍为 `incomplete`。

## 运行时就绪条件

远端 environment 的 `ase_neb` Backend binding 必须选择由运维人员管理的版本化环境中的 Python
解释器。该解释器必须能导入 ASE、NumPy，以及与准备计算的 TSPi 版本一致的
`ts_agent.backends.ase_neb_runner`。在 Backend binding 的环境变量中将 `TS_ASE_NEB_XTB`
设为已验证的 xTB 可执行文件，不依赖交互式 shell 的 `PATH`。

部署或修改 environment 后、首次提交 NEB 前运行 `TSPi --check-remote`。解释器缺失、
导入失败、runner 版本不一致或 xTB 探测失败都属于运维失败，不能作为反应路径
证据。不得从计算作业中安装包，也不得把软件安装到研究工作区。按照
[ASE NEB 部署流程](../../../docs/INSTALLATION.md#deploy-the-ase-neb-runtime-with-pixi)
操作，并且只有登录节点和计算节点冒烟检查都通过后才能切换 Backend binding。
