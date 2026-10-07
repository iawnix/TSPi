# t001 重装配置与执行边界修复计划

状态：待实施。2026-10-07。

本次只制定计划。实施时以本计划替代此前“邮件预检单独创建计算 Job 节点”的方案。

## 1. 目标与已确认原因

用户确定的边界：邮件流程通过原生 bash 调用邮件 CLI；job_start、job_status、job_collect、job_cancel、job_probe、job_reconcile 面向计算任务。

已确认的问题：

- 重装前 t001 的 Job 元数据已有完整 Conda 绑定；重装导入的 `/home/iaw/DATA/tspi_install_config/job.toml` 却没有这些绑定。安装配置源与有效运行配置不同步。
- 安装校验接受 command-only 科学后端，method-selection helper 却要求结构化 Python binding，并拒绝旧 pyscf.command，造成“安装成功、首次计算即失败”。
- 旧运行通过 bash 完成邮件配置检查；新运行按邮件 Skill 的 Job 指引，将检查挂到依赖三个计算结果的发送节点，触发 research_node_not_ready。
- 邮件 Skill、架构文档和 test_email_job_flow.py 都把邮件当作 Job；报告 Skill 也使用 Job。这需要一致修正，不能只改一条提示词。
- 原生 bash 仍受研究生命周期约束；全局 blocked/terminal 时会被拒绝。单纯替换工具名称不能解决交付顺序问题。

审查证据：`/home/iaw/debug/tspi-test-env/t001-new-install-audit/report.md`；旧运行证据：`/home/iaw/debug/tspi-test-env/t001-analysis/entries.json`。

## 2. 执行职责

| 操作 | 执行方式 | 持久化结果 |
| --- | --- | --- |
| 科学计算、优化、单点能、科学分析任务 | job_* | Job、Attempt、计算输出及 Artifact |
| 计算请求准备、参数帮助、环境配置读取 | bash + 已安装 helper | 请求文件、诊断记录 |
| 从已有结果整理报告、格式化已有数据 | bash + report builder | 报告文件及 Artifact |
| 邮件 check / prepare / send / status | bash + email_cli.py | 请求文件、投递回执及必要 Artifact |

报告步骤若需要额外科学计算，该计算另走 Job；纯文档生成不创建 Job。邮件交付可以保留 ResearchNode 记录完成情况，但不创建计算 Attempt，也不需要为了预检新增 Job 节点。

Job Runtime 底层保留通用 argv 执行能力。在 Agent 可见的工具说明、系统提示和 Skill 中明确计算用途，不靠分析 shell 字符串或 `metadata.no_send` 判断命令语义。保留既有 Job 的读取、回收与核查能力，包括历史邮件/报告 Job。

## 3. 实施步骤

### P1：修复安装配置源和计算就绪校验

1. 备份源 job.toml 与安装内 job.toml，记录摘要；从旧 Job 元数据核实本地 Conda 绑定。
2. 校验现有 `/home/iaw/soft/tspi/envs/cf22d-20261007`、`runner-20261007` 及对应锁文件的实际依赖与一致性。已有路径存在不等于环境已验证。
3. 迁移本地环境配置：明确 manager、conda_executable、prefix、lock_ref；PySCF 移除旧解释器 command；保留 xTB/Gaussian 可执行程序和必要激活脚本。
4. 在通用配置结构校验之外，提供科学后端就绪校验，安装器与 helper 共用必要规则。校验环境级继承、后端覆盖、遗留 PySCF 绑定和缺失字段；不把化学后端规则散落进通用 Job Runtime。
5. 本地就绪检查验证 Conda、锁文件、目标环境及必需依赖，并准备最小请求；这些检查不提交真实计算。
6. 安装结果区分“已导入”“静态校验通过”“本地就绪”“远程未验证”。默认本地计算不就绪时，安装前置检查应明确失败，不能输出整体可用。远程条目逐项报告，不能假称已验证，也不自动连接远端或猜测配置。
7. 同步通过验证的配置到安装源和安装目录。记录配置摘要/就绪结果，并在后续安装中检测漂移；不自动把运行配置覆盖回源文件，不静默合并冲突。

主要文件：`packages/job-runtime/job_runtime/config_contract.py`、method-selection helper、`scripts/install_wizard.py`、`scripts/install_configured.py`、`config/job.schema.json`、安装文档与对应配置测试。环境维护复用 `scripts/install_job_environment.py` 的锁与校验机制。

### P2：邮件全流程改为 bash

1. 同步修改邮件中英文 Skill 与投递说明：check、prepare、send、status 都通过原生 bash 调用 `"$TSPI_PYTHON" <安装的邮件脚本路径>`，继承 TS_NOTIFICATION_CONFIG。
2. 请求、检查结果和回执写入工作区 reports/email 下，设置有界超时。结束或失败后检查持久化回执，不以 bash 退出码单独判断投递结果。
3. 保留现有投递库的内容摘要、稳定 notification_id、锁、去重与 unknown 恢复语义。bash 重试沿用同一通知身份，不能改 ID 后重复发送。
4. Skill 明确：配置预检可以在计算前执行；实际发送遵守用户的交付要求。当前“完成后发结果”的任务需在结果/报告就绪后发送。邮件失败单独记录，不回滚完成的计算。
5. 对齐核心 orchestration、系统提示、job_* 工具描述和架构文档，清除“所有执行/所有 Skill 都必须走 Job”的冲突表述。

主要文件：`extensions/email/SKILL*.md`、`extensions/email/references/email_delivery*.md`、core orchestration、Agent 工具描述/提示词、`docs/ARCHITECTURE_BOUNDARIES.md` 及相关中英文说明。CLI 与 notify_lib 仅在发现实际功能缺口时修改。

### P3：报告生成与研究生命周期衔接

1. report Skill 通过 bash 直接调用现有 build.py，使用明确的输入结果路径和新的空输出目录；保留科学结果验证、输入摘要、矩阵完整性和 Artifact 登记。
2. 从公开 Skill 和新调用路径移除报告 Job 准备流程，清理仅用于该流程的 helper、资源索引与测试引用；历史报告 Job 仍可读取/收集。
3. ResearchNode 仍记录报告/交付目标和证据，但纯报告/邮件不生成计算 Attempt，不要求 job_collect 或 Monitor 唤醒。
4. 工作流顺序明确为：计算输出核验 → 报告 → 已授权邮件投递/记录交付阻塞 → 最终 checkpoint。不能在仍有交付动作时提前进入 terminal。
5. 计算失败时先判断独立工作和已授权交付是否仍可继续，再决定全局 blocked；仅“完成后发结果”不自动扩展为发送失败通知。
6. 保留 bash 的 execution_control 属性和全局生命周期门禁。已有 blocked/terminal 会话通过正式恢复 checkpoint 后继续，不把 bash 标成只读，不新增邮件专用门禁绕过。

主要文件：report Skill/脚本资源、orchestration 与 research-state 指引、native tool metadata 的说明和生命周期回归测试。是否需要改状态机实现，由现有正式恢复路径的验证结果决定。

### P4：回归验证

所有测试环境、安装、临时目录置于 `/home/iaw/debug/tspi-test-env`。真实软件环境仍在 `/home/iaw/soft`；测试使用独立副本或测试环境。

- 配置：旧 command-only 科学配置在安装预检中给出可操作错误；有效环境级/后端级绑定均可生成三种方法请求；缺失锁、依赖错误、安装源漂移不能被报告为就绪。
- 重装：以修复后的源配置安装到隔离目录，核对绑定及摘要；重复安装仍能准备三个计算请求。确保运行环境检查没有被 Host Python 的成功探针代替。
- 邮件：将 test_email_job_flow.py 改为 bash CLI 流程测试，使用本地 TLS SMTP 接收器，验证 check → prepare → send → status，重复发送只接收一封，失败和 unknown 的处理正确。
- Harness：在科学计算节点依赖未完成时，正常活动会话的 bash 邮件预检可执行；计算 job_start 仍受依赖门禁；全局 blocked/terminal 仍拒绝 bash，正式恢复后允许继续。
- 报告：已有结果通过 bash 生成报告，输入验证、输出目录约束、Artifact 登记保持有效。
- 完整流程：最小计算 Job → collect → bash 报告 → bash 邮件到测试接收器 → checkpoint。邮件/报告不新增 Job/Attempt/Monitor 事件；计算仍有完整 Job/Attempt 记录。
- 执行现有相关 Python/Node 测试及文档、Skill、资源摘要、打包检查。测试服务在 finally 中停止并清理，确认无残留进程。

### P5：部署与恢复 t001

1. 通过验证后构建、安装修复版本；记录源码版本、配置摘要和依赖校验结果。
2. 修复本地绑定并同步安装源。保留当前 t001 输入、诊断、checkpoint 和会话，不重建工作区。
3. 用正式恢复 checkpoint 进入可编辑状态，解决配置问题对应的 issue，恢复计算节点并更新交付策略。所有修改走 Research State API，不直接编辑数据库或状态 JSON。
4. 从请求准备重新执行三个计算；报告和邮件按新 bash 流程继续。正式邮件仅依据已有用户授权及实际结果发送；计划阶段和隔离测试不发送真实邮件。
5. 记录最终结果以及 Job/Attempt、邮件回执和 Monitor 状态，确认不存在重复提交、重复投递或僵尸进程。

## 4. 验收标准

1. 从维护后的配置源重装即可准备并运行三个本地计算，安装阶段能识别本次失效配置。
2. 邮件四个子命令和纯报告生成均走 bash，正常活动会话的邮件预检不再受计算节点依赖影响。
3. 科学计算仍走 job_*，研究节点依赖约束保持有效。
4. 邮件投递依靠持久化回执与稳定身份恢复，超时或重试不会盲目重复发送。
5. t001 可从现有证据和状态恢复完成；配置源、安装配置及文档/测试约定一致。
