# 科学 Job 合同

Skill 负责科学输入、argv、解析与验证，使用随包安装的脚本，不需要科学注册表或 workflow catalog。

## 提交

method-selection/scripts/prepare_job.py 读取 job.toml，返回 command（argv）、platform（配置的执行环境）、environment（进程环境变量对象）、inputs（source/destination 文件或目录映射）、outputs（path、required、min_bytes、media_type）及普通 metadata。补充 node_id、timeout_seconds 和需要的 metadata.resources（cpus、memory_mb、walltime）后 job_start。cwd 是隔离 Job 根下的相对子目录，不是任意工作区路径。

输入复制为带路径和摘要的快照，保持脚本 import 目录结构。Runtime 负责本地/远程进程控制；Skill 可以在 Job 内同步调用科学程序，不能自行后台化或另行提交调度任务。

## 环境

job_probe 只检查平台可达，不证明科学方法可用。command 和 activation_script 决定实际程序。CF22D 通过 scripts/doctor.py 检查依赖及方法构建，每个选定环境分别执行。远程包装脚本的 Python 必须明确配置；缺依赖不回退系统 Python 或更换方法。

## 证据

job_start 返回不同的 job_id 和 attempt_id；等待检查点引用真实 Attempt。job_collect 返回退出事实、output_validation，以及研究 Job 登记的 Artifact。退出 0、文件齐全、科学验证通过是不同事实；登记 Finding 前读取 Skill result.json 和日志。

artifact_derive 只记录派生描述，不执行分析。通过 Skill 脚本执行后登记真实结果，artifact_link 持久关联证据。科学输入/设置改变需新 Attempt；不确定提交用 job_reconcile 恢复，不能自动重提。
