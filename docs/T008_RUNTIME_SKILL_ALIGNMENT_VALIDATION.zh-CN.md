# t008 修复与验收记录

日期：2026-10-07（北京时间）。实现与安装验收已完成；此文记录实测范围与剩余行为限制。

## 已实现

- job.toml 结构化 Conda Python 绑定。安装校验、Job Runtime 与 Skill helper 共用公开解析器；backend.python 优先，否则继承 environment.python。清理宿主 PYTHONHOME/PYTHONPATH，禁用用户 site-packages。
- 安装维护脚本 scripts/install_job_environment.py：显式 Conda lock、可选带哈希的 pip 离线 wheel 清单、prefix 互斥锁、依赖验证及原子环境收据。不在研究回合安装依赖。
- Skill 错误路径返回准确定位信息；job_start 提交前也检查不存在的安装包绝对资源路径，防止错误脚本路径先变成失败 Job；core Skill 明确普通探测无需 Finding、邮件先检查配置、独立计算继续。FactFinding 要求真实证据引用和 provenance；错误返回恢复指引。
- Research State 统一计算就绪节点、阻塞节点、运行 Attempt 和工具/唤醒准入。Host 保留调用串行化和阶段标记，移除与 State 冲突的阶段准入图。缺失权威准入结果时 Worker 拒绝执行。
- 全局用户等待不能覆盖独立就绪工作或运行任务；混合等待用阻塞 Node 加真实 Attempt 的 waiting_external。Monitor 暂缓事件保存状态 token，状态未变化时不重复唤醒。
- 公共工具表和 checkpoint disposition 生成中英文引用并加入漂移检查；memory 继续是 State 的可重建投影。
- Torque 作业未能写退出回执时，可从已完成调度记录恢复 exit_status，避免目录失败后永久 unknown。

## 环境落地

| 环境 | Conda | runner / CF22D prefix |
| --- | --- | --- |
| local | /home/iaw/soft/miniconda/26.7.1-1/bin/conda | /home/iaw/soft/tspi/envs/{runner,cf22d}-20261007 |
| remote | /home/agent/soft/tspi/conda/bin/conda | /home/agent/soft/tspi/envs/{runner,cf22d}-20261007 |

各机器 locks 目录保存显式 Conda 锁、CF22D 的 pip 版本/哈希清单及 wheel。CF22D 环境不依赖 Host 的 tspi 包。远端旧系统使用兼容 glibc 的 Miniconda，CF22D activation 预加载本 prefix 的 OpenMP 库。

实际 PBS 检查发现 /data2/agent-1w 只在登录节点可见；远程任务根迁移为共享 /home/agent/ts-remote-workspaces。测试使用允许的 fata 队列；batch 当时无满足条件的空闲节点。软件路径在计算节点可访问。旧任务及原始 t008 记录未重写。

## 已通过验证

- Python unit、contract、安装配置测试：239 项通过（含隔离 TLS SMTP 邮件 Job 流程）。
- Worker、路径 guard、Host 生命周期和 Monitor 重点回归通过（14 项）；Node fast 全部 21 项通过。安装包 Worker 完整流程通过，并额外覆盖 current 符号链接入口。安装路径先解析真实路径，避免 Worker 入口身份比较失败。
- 本地与真实 PBS 计算节点均完成水分子的 GFN2-xTB opt-sp、CF22D/def2-SVP opt-sp（grid level 3）及 M062X/6-31G** opt-sp。检查科学 validated、优化收敛、几何哈希、解释器 prefix 和环境收据，不仅检查退出码。CF22D 参数为安装烟测设置，不代表用户任务的最终计算标准。
- 邮件 check → prepare → Job send → 幂等重试，在本机隔离 TLS SMTP 接收器通过，只捕获一封测试邮件。没有向真实收件人发送邮件。
- 第一轮真实 CPA/gpt-6-luna 自主选择 Skill、计算水分子 xTB、检查已有收件配置、生成报告并 terminal 关闭。该轮仍有路径/字段错误及 Host 阶段冲突，不能称为零错误行为验收；Host 冲突和关键字段提示已据此修正。
- 第二轮安装版真实模型评测：38 次工具调用，完成一次科学 opt-sp、邮件配置检查、注册报告和 terminal 关闭；只有一条原始用户消息，没有 Harness 补救续跑或重复计算。两次工具参数错误（cwd、artifact_link relation）被自主纠正；另有两次错误邮件路径 Job 失败后恢复。随后补充了 job_start 的不存在资源预检并通过针对性测试，因此不把本轮行为评测包装为零错误，也不声称预检补丁后又做了一次完整真实模型评测。

## 边界与证据

continue_required 仍是合法持久化 checkpoint；此次没有新增独立 Host 定时续跑器或 Skill next_run 状态库。需要跨回合等待的外部作业由现有 Monitor 事件驱动；独立就绪工作要求 Agent 在当前回合继续。此点是相对初始方案的明确范围收敛。

日志与完整测试产物在 /home/iaw/debug/tspi-test-env/t008-repair；第一轮真实模型记录在 /home/iaw/debug/tspi-test-env/eval008，安装版记录在 /home/iaw/debug/tspi-test-env/eval008c。测试服务均在 finally 中关闭；远程烟测作业收集后取消并删除专属暂存目录。软件环境是生产环境，保留供后续任务使用。

## 最终安装

生产安装 /home/iaw/ResearchAgent 已切换为 `0.17.0-sha256-137af8766dd78f3d`；Host 服务已重启，t008 会话只读连接验证 online=true、streaming=false、无运行时故障。配置只有 local、remote。旧配置与安装状态备份位于测试目录 production-backup。
