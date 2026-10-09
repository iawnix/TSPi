# 科学 Job 合同

领域扩展负责科学输入、argv、解析与验证；manifest 声明执行入口，Skill 说明选择条件和结果解释。

## 提交

`"$TSPI_PYTHON" -m tspi_runtime.executors` 将扩展声明的执行入口与 job.toml 中的命名绑定组合，生成含 argv、目标环境、进程变量、固定输入和输出的请求。检查文件后，将返回的 request_file/request_sha256 连同 node_id 和可选 timeout_seconds 交给 job_start。资源默认值在准备前配置到 job.toml。Runtime 把 prepared_ref、提交意图和 Attempt 一起登记；准备命令不写 Research State。

输入复制为带路径和摘要的快照，保持脚本 import 目录结构。Runtime 负责本地/远程进程控制；Skill 可以在 Job 内同步调用科学程序，不能自行后台化或另行提交调度任务。

## 环境

job_probe 只检查平台可达，不证明科学方法可用。command 和 activation_script 决定实际程序。CF22D 通过声明入口 `chemical.cf22d-doctor` 准备 Job，逐个选定环境检查依赖及方法构建。远程包装脚本的 Python 必须明确配置；缺依赖不回退系统 Python 或更换方法。

## 证据

job_start 返回不同的 job_id 和 attempt_id；等待检查点引用真实 Attempt。job_collect 返回退出事实、output_validation，以及研究 Job 登记的 Artifact。退出 0、文件齐全、科学验证通过是不同事实；登记 Finding 前读取 Skill result.json 和日志。

artifact_derive 只记录派生描述，不执行分析。通过 Skill 脚本执行后登记真实结果，artifact_link 持久关联证据。科学输入/设置改变需新 Attempt；不确定提交用 job_reconcile 恢复，不能自动重提。
