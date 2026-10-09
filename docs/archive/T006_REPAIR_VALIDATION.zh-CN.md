# t006 核心修复验收记录

> Historical archive / 历史归档：本文记录旧设计或一次性验证，不是当前接口合同，也不代表本次重构已通过验收。当前设计见 [Research Memory plan](../RESEARCH_MEMORY_DESIGN_AND_IMPLEMENTATION_PLAN.zh-CN.md)。

日期：2026-10-06。范围：当前工作树的源码改造与隔离测试。修复方案见 [原始方案](T006_SKILL_JOB_REPAIR_PLAN.zh-CN.md)。

## 已实施的修复

| 范围 | 实施结果 |
| --- | --- |
| 科学执行资源 | 从 Git 历史迁回 CF22D runner、xTB/Gaussian 输入和解析逻辑，去除旧 Provider 依赖；补齐可执行 CLI、共享验证、结构化结果和行为测试。三个方法支持显式优化后独立单点。 |
| Skill 环境与路由 | method-selection 的 prepare_job.py 读取 job.toml，使用配置的解释器、软件和激活脚本，生成通用 job_start 请求；保留目录结构暂存脚本、辅助模块与输入。远程包装脚本要求明确的 Python 路径。 |
| 资源完整性 | Skill manifest 固定 resources.json 摘要；加载器校验入口、脚本及共享模块摘要，打包清单包含执行资源；提供摘要更新脚本。 |
| 本地执行 | 独立 supervisor 保存真实退出码，脱离 Host 仍执行超时控制，支持重启后状态查询和取消；缺失/空产物单独报告，不覆盖进程退出码。 |
| 远程执行 | 区分 queued/running/held/unknown，暂存完整输入目录，映射 CPU、内存、walltime，持久保存 scheduler.id，支持提交响应丢失后的回执恢复；取消失败不假报成功。 |
| 提交与状态 | 提交前持久化意图；稳定 requestId 防止重复提交；建立 Job 与真实 Attempt 关联，经统一事务入口更新执行事实。收集时登记日志/结果 Artifact，持久化 Evidence Link。 |
| Agent 生命周期 | 等待外部任务时允许查询、收集和受限证据写入；已规划且独立的 ready Node 可继续执行；研究决策门禁继续生效。 |
| 后台恢复 | 补齐通用 monitor CLI 与持久唤醒队列，只在终态或未知状态变化时唤醒 Agent；不由 Monitor 直接发送邮件。 |
| 邮件 | 迁移为 email Skill 的 check/prepare/send/status 脚本；冻结收件人、附件摘要及发送身份，持久保存回执，阻止对发送结果未知的请求盲目重发。删除内建 notify 工具、通知 dispatcher 和 email Provider 入口。 |
| 报告与边界 | 恢复 report Skill 的结构化汇总；缺失结果标为未验证，不跨方法排名绝对能量。删除空 chemical 工具工厂，chemical/email manifest 不再声明 Provider；通用兼容设施不等于科学执行注册表。 |

科学方法和收敛判断仍由 Skill 提供，Job Runtime 只负责通用执行与文件事实。没有恢复 chemical Capability 注册或 calculation_* 工具。

## 自动化验证

测试环境和证据均位于 `/home/iaw/debug/tspi-test-env`，没有向生产安装部署改动。

| 检查 | 结果 | 证据（相对 t006-repair 测试目录） |
| --- | --- | --- |
| Python 单元与合同测试 | 166 项通过 | pytest-final.log |
| Node 加载器、工具清单、生命周期、Monitor 定向测试 | 25 项通过 | node-release.log |
| 安装包检查 | 通过，451 个文件 | package-check-final.log |
| public surface / architecture / skills lint | 均通过 | final-checks.log |
| Skill quick_validate | cf22d、xtb、gaussian、method-selection、report、email 均通过 | 使用已有 PySCF Python 的 YAML 依赖校验 |

测试覆盖进程异常退出、无轮询超时、重启取消、缺失/空输出、重复 requestId、研究状态关联、证据关系、远程队列状态/回执恢复、邮件去重和脚本资源篡改。邮件传输使用模拟实现，没有发送真实邮件。

## 真实科学计算

使用测试水分子，通过修改后的 Job Runtime 执行本地 opt-sp 工作流；各步骤保存日志和结构化结果，SP 使用优化后的坐标，各方法均报告 validated=true。

| 方法 | 基组 | 独立 SP 能量（hartree） | 结果 |
| --- | --- | --- | --- |
| CF22D | 6-31G** | -76.37315882854823 | 优化及单点均通过 |
| GFN2-xTB | 方法内建 | -5.070544437761 | 优化及单点均通过 |
| M062X / Gaussian | 6-31G** | -76.3839392199 | 优化及单点均通过 |

这些不同方法的绝对能量不能用于方法精度排名。水分子验证也不代表复杂反应、过渡态等全部工作流已验收。

原始结果在 `/home/iaw/debug/tspi-test-env/t006-repair/matrix/runs/jobs/job_repair_local_<method>/results/`；汇总在 `/home/iaw/debug/tspi-test-env/t006-repair/local-report/report.md` 和 report.json。该矩阵直接调用通用 Runtime，真实 Agent 的规划、状态更新与邮件串联没有端到端重跑；状态关联另由自动化测试验证。

## 远程验证与清理

三个远程测试 Job 已完成 SSH 连接、脚本与辅助模块暂存、明确解释器的入口导入检查、Torque 提交、资源配置及排队状态读取。登录环境没有裸 python3，因此包装脚本使用配置的 `/home/agent/soft/pyscf/current/bin/python`。

| 本次测试 Job | 调度器 ID | 清理结果 |
| --- | --- | --- |
| job_repair_cluster_1w_cf22d | 209806.cluster.hpc | qdel 成功，确认 C 终态，测试目录删除 |
| job_repair_cluster_1w_xtb | 209807.cluster.hpc | qdel 成功，确认 C 终态，测试目录删除 |
| job_repair_cluster_1w_gaussian | 209808.cluster.hpc | qdel 成功，确认 C 终态，测试目录删除 |

三项在取消前一直为 Q，**没有产生远程科学计算结果，不记为远程计算通过**。调度器可暂时保留 C 历史记录，它不是仍在执行的任务。清理证据为 `/home/iaw/debug/tspi-test-env/t006-repair/remote-cleanup.json`。本次本地 supervisor 和可选依赖安装进程均已退出；未启动持续服务。保留测试日志与本地结果用于复核。

## 剩余验收边界

1. 生产 ResearchAgent 尚未部署；原 t006 工作区、会话及历史调度任务 209763/209764/209765 未修改，也没有重跑原任务。
2. 远程三个方法的完整 opt-sp、跨环境结果比较、部署后的 Agent 自动唤醒到报告/邮件全过程仍需独立验收。
3. 调度器强制杀死任务且未留下退出回执时，仍保守返回 unknown；未实现依赖调度记账系统推定退出结果的逻辑。
4. CREST、NEB、IRC、绘图及其他历史领域能力没有全部恢复。保留的高级解析或参考代码不代表对应工作流已经可执行或通过验收。
5. 邮件真实 SMTP 发送未测试。是否发送仍由用户授权和 email Skill 流程决定。
