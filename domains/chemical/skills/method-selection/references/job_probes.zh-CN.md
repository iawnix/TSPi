# 计算环境合同

`job_start` 同时管理本地和远端目标的计算生命周期。远端 adapter 是安装级绑定的
OpenSSH/SCP 与 Torque 传输层，不是另一套公共计算生命周期。使用 `job_probe` 对所选 `platform` 做有界可用性检查。

## 安装级策略

推荐使用 `job.toml` 作为共享策略文件。每个环境声明 `kind` 和 `backends` 表；
`kind = "remote"` 的环境还拥有 SSH host/config、远端根目录、调度器命令、队列、资源上限、
激活、scratch 策略和进程环境。本地与远端环境都在同一个文件中定义。计算请求选择一个
命名环境，以及不超过其配置上限的资源。

该文件是 local/remote 唯一的环境权威。不要再增加独立的 `.pi/remote.toml` registry，也不要
从某个主机目录推断远端环境。配置的环境名作为 `job_start` 的 `platform` 字段传入。环境的可选软件 metadata 只描述绑定和就绪状态，不是 workflow registry
或除探测和传输检查之外的启动门禁。

`job_probe` 检查平台可用性，不证明科学方法就绪。核实所选 backend 的命令、激活脚本和
Python 绑定；需要时执行程序的有界 help/version 检查或 Skill 专用 doctor。
CF22D 的 [doctor.py](../../cf22d/scripts/doctor.py) 检查配置的 PySCF 环境和方法构造，
不证明其他程序就绪。当前没有内置 NEB 就绪探测或 workflow registry。
不要在研究 workspace 中安装科学依赖。

## 隔离

远端目录由 Job 执行身份与工作区路径推导。上传 manifest 绑定普通文件、
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
- 分别核验所选平台和科学命令；仅有 SSH 连通性不足。
- 调度完成后检查程序终止状态和必需输出。
- 收集输出，在本地核验并解析后再记录研究记录。
