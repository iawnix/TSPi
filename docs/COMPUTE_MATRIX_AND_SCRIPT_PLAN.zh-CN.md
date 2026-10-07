# 计算矩阵与 Skill 脚本

科学任务由 Agent 根据 Skill 组织，再通过通用 job_start 执行。当前 CF22D、xTB、Gaussian Skill 均有 scripts/run.py，可执行 opt、sp、opt-sp；没有独立的计算 Provider 或 script.bash capability。

三种方法、两个环境、优化后单点表示 12 个逻辑步骤。可使用六个 opt-sp Job，但每个组合 Job 必须保留两步记录、原始日志及结构依赖。单点使用同方法、同环境的优化结构；优化失败不能继续单点。

method-selection/scripts/prepare_job.py 读取安装级 job.toml 的 command、activation_script、environment，为配置解释器和程序准备 argv，以及完整脚本依赖集的暂存映射。它只生成请求。远程 xTB/Gaussian 包装器需要 --python 或 environment.python 指定 Python >=3.10，不假定登录 PATH 有 python3。

Job 的 nodeId 在提交前绑定真实 Attempt，返回 job_id 和 attempt_id。使用 Attempt 引用保存 waiting_external，job_status/job_collect 保留执行事实和输出完整性；Skill result.json 的 validated、steps 与日志证明科学步骤是否完成。

报告 Skill 汇总实际结果并记录来源摘要。邮箱配置问题只阻塞 email Skill；计算结果不回滚。邮件由 Agent 按用户授权通过本地 bash 调用邮件 CLI 发送，Monitor 只唤醒同一会话。

完整修复范围、历史证据及分阶段验收见 [t006 修复方案](T006_SKILL_JOB_REPAIR_PLAN.zh-CN.md)。
