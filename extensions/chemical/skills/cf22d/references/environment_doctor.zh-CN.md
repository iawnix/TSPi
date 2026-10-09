# CF22D 就绪检查

首次运行或修改环境后，用 `tspi_runtime.executors` 准备 `chemical.cf22d-doctor@1`，再提交到有时间上限的 job_start；声明入口使用配置的 PySCF 解释器和激活脚本。它检查 PySCF、geomeTRIC、色散依赖及实际 CF22D/D3 构建，不执行 SCF 或优化，保存 stdout 作为检查证据。

job_probe 只证明平台可达；本地成功不证明远程可用。计算请求的 tspi_runtime.executors 辅助脚本负责读取对应环境绑定。研究 Job 不修改共享环境或临时安装依赖。

就绪不等于计算结果有效或必然收敛。检查失败时保留底层原因，修复环境后再运行。
