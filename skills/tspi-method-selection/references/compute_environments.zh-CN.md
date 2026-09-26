# 计算环境合同

`compute_run` 同时管理本地和远端目标的计算生命周期。远端 adapter 是安装级绑定的
OpenSSH/SCP 与 Torque 传输层，不是另一套公共计算生命周期。公共环境查询是
`compute.environments`，通过 `/compute` 与 `compute_environment` 暴露。

## 安装级策略

推荐使用 `compute.toml` 作为共享策略文件。每个环境声明 `kind` 和 `backends` 表；
`kind = "remote"` 的环境还拥有 SSH host/config、远端根目录、调度器命令、队列、资源上限、
激活、scratch 策略和进程环境。本地与远端环境都在同一个文件中定义。计算请求选择一个
命名环境，以及不超过其配置上限的资源。

使用安装级 `TSPi --check-remote` 做只读诊断：

- `status`：只检查 SSH 连通性；
- `doctor`：检查 SSH、调度器、存储与已注册软件；
- `queues`：有边界的队列视图；
- `nodes`：有边界的计算资源视图。

首次远端计算前，或配置发生变化后，运行 `TSPi --check-remote`。对于 `ase_neb`，
`doctor` 还会使用配置的 Python 导入 ASE 与 TSPi runner，并执行配置的 xTB 程序版本探测。
三者全部可用时环境才算就绪。
对于 `pyscf`，必须绑定包含 PySCF、geomeTRIC、`pyscf-dispersion` 和 TSPi runner 的专用
Python 解释器及 activation script；doctor 还会探测 `CF22D` DFT 构造器。PySCF kernel
不会在计算过程中向宿主 Python 安装依赖，也不会从宿主 Python 猜测科学软件包。

## 隔离

远端目录由 workspace identity、ResearchNode 和 intent 推导。上传 manifest 绑定普通文件、
大小、SHA-256、命令、环境、资源、预期 Artifact 和 submission ID。远端文件提供执行副本；
收集阶段把已声明输出下载到本地 workspace。

## 控制生命周期

Submit 在调用 Torque 前持久化生效前 staging 状态。一旦调度请求开始，传输失败的效果可能
不确定。即使之后队列/历史查询失败，也要保留任何已知 job ID 和持久化 submission record。

Cancel 同样区分已知未生效、已知取消和效果不确定。当任务从队列消失时，检查其回执与
声明的输出以确定实际情况。

Inspect 可以组合持久化回执、调度器状态、程序状态和已声明 Artifact 的有边界 tail。
Collection 遵循不可变 Artifact manifest，即使调度器历史不可用也能工作。

## 核验结果

- 在下一次控制动作前协调确认未知的 submit 或 cancel 结果。
- 从配置的环境和 intent 解析远端路径与命令。
- 使用 `TSPi --check-remote` 同时检查 SSH、调度器与软件就绪状态。
- 调度完成后检查程序终止状态和必需输出。
- 收集输出，在本地核验并解析后再记录 Finding。
