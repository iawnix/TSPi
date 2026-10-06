# TSPi 最终架构说明

本文描述当前实现的最终架构。系统采用单一 Pi Agent loop，科学领域通过 Skill 提供操作说明、脚本和参考资料，长时间执行通过 Job Runtime 完成，研究事实和判断通过 Research State 保存。

## 设计目标

TSPi 将通用 Agent 能力与研究语义分开：

- Pi 负责对话、工具调用、上下文和恢复。
- Skill 负责领域知识、输入构造、命令示例和输出解释方法。
- Job Runtime 负责任意命令的长时间执行、状态查询、取消、收集和恢复。
- Artifact Store 负责保存原始文件、派生文件和内容摘要。
- Research State 负责 Phase、Claim、Node、Finding、Gate、Assessment、Revision 和生命周期记录。
- Monitor 只负责在外部 Job 状态变化时唤醒同一个 Agent loop。

系统不要求每个程序都有内置解析器。命令成功执行只产生原始 Artifact，不自动形成 Finding，也不自动支持 Claim。

## 运行时组成

```text
Pi Agent loop
  ├─ bash / write / edit
  ├─ research_read
  ├─ research_change
  ├─ research_strategy
  ├─ research_interpretation
  ├─ research_checkpoint
  ├─ job_start / job_status / job_collect / job_cancel
  ├─ job_probe / job_reconcile
  └─ artifact_register / artifact_create / artifact_read
      / artifact_derive / artifact_link

Skill instructions
  ├─ input templates and command construction
  ├─ optional parser/analyzer scripts
  └─ references and scientific validation rules

Research State Runtime
  ├─ canonical filesystem projections
  ├─ ChangeSet validation and optimistic revision checks
  ├─ Claim assessment and revision history
  └─ liveness and research obligations

Job Runtime
  ├─ local process platform
  ├─ installation-provided remote platform adapters
  ├─ durable receipt and status files
  └─ output collection and digest calculation
```

Pi 是唯一的 Agent Runtime。系统不创建专用的计算 Agent 或审查 Agent，也不通过领域 provider 注册 Agent 工具。

## Skill 规范

Skill 位于 `extensions/core/skills/` 或扩展自己的 `skills/` 目录。每个 Skill 至少包含：

- `SKILL.md`：短入口说明、适用条件和操作步骤。
- `SKILL.zh-CN.md`：中文入口说明。
- `references/`：按需加载的详细知识。
- 可选的 `scripts/`、`templates/` 和 `analyzers/`：由 Agent 通过普通文件和 shell 工具调用。

Skill 可以描述 Gaussian、xTB、CREST、PySCF、ASE-NEB 等程序的输入格式和输出判断方式，但不向运行时注册固定能力目录。程序是否安装、命令是否可执行，由 `job_probe` 或实际 Job 结果决定。

Skill 的推荐执行流程：

1. 读取输入和研究目标。
2. 在工作目录写入输入文件和运行脚本。
3. 使用 `job_probe` 检查执行平台的基本条件。
4. 使用 `job_start` 启动任意 argv 命令。
5. 使用 `job_status`、`job_reconcile` 观察状态。
6. 使用 `job_collect` 收集 stdout、stderr 和声明的输出文件。
7. 使用 `artifact_register` 登记原始输出。
8. 使用 Skill 脚本或 `artifact_derive` 产生可复核的派生数据。
9. 由 Root Agent 通过 `research_interpretation` 写入 Finding、ClaimAssessment 或 ClaimRevision。

## Job Runtime

Job Runtime 位于 `packages/job-runtime/job_runtime/`，公开模型包括：

- `JobSpec`：命令、工作目录、输入、输出、环境和身份关联。
- `JobReceipt`：Job ID、平台、工作目录、Node/Attempt 关联和持久化位置。
- `JobStatus`：submitted、running、succeeded、failed、cancelled、timed_out 等状态。
- `JobOutput`：声明的相对输出路径、媒体类型和是否必需。
- `JobRuntime`：统一的六个 Job 操作。
- `LocalProcessPlatform`：本地 argv 执行、状态持久化和输出摘要。
- `RemoteExecutionPlatform`：安装级远程平台实现的抽象边界。

Job Runtime 不解析科学格式、不修改 Research State，也不判断 Claim 是否成立。Job receipt 和 `status.json` 允许新的进程恢复状态；`job_reconcile` 用于外部平台状态与本地 receipt 对齐。

`packages/research-compute/research_compute/execution.py` 提供 `ExecutionRequest` 和 `ExecutionService`。它只负责把 Research 身份传给 Job Runtime，不重新引入领域 provider、能力目录或格式门禁。

## Artifact Store

Artifact Store 位于 `packages/artifact-store/artifact_store/`。Artifact 是文件证据的物理载体，具有：

- 稳定 ID 和 SHA-256 摘要。
- 媒体类型、大小和来源路径。
- 原始 Artifact 与派生 Artifact 的关系。
- 与 Node、Finding 或 Claim 的显式 link。

`artifact_register` 登记已有文件，`artifact_create` 写入内存内容，`artifact_read` 读取受限内容，`artifact_derive` 保存由已有 Artifact 计算出的派生数据，`artifact_link` 建立研究对象与证据之间的关系。

Artifact 不等于 Finding。Artifact 记录“产生了什么文件”，Finding 记录“这些文件支持什么解释”。

## Research State

Research State 位于 `packages/research-state/research_state/`，是研究事实的唯一来源。主要对象包括：

- Phase：研究阶段和目标。
- Claim：可被支持、反驳或修订的假设。
- Node：一个有明确目标、输入和完成条件的工作单元。
- Finding：带来源和 provenance 的事实或问题。
- Gate：对 Node 或 Claim 的显式判断条件。
- ClaimAssessment：对现有 Claim 的 supported、contradicted 或 inconclusive 评估。
- ClaimRevision：创建新 Claim 并保留旧 Claim 历史。
- LifecycleAction：需要执行、延后、阻塞或完成的研究动作。
- Checkpoint：Agent turn 的继续、等待、阻塞或终止状态。

Research State 只接受显式 ChangeSet。ChangeSet 必须带 rationale、basis refs 和预期 revision。Finding 必须带 `source_refs` 与 provenance。Claim 状态不会因为 Job 成功而自动改变。

## 研究闭环

Research Agent 的核心循环是：

```text
提出 Claim
  ↓
创建 Node 和验证目标
  ↓
Skill 构造输入与命令
  ↓
job_start
  ↓
job_status / job_reconcile
  ↓
job_collect
  ↓
artifact_register
  ↓
Skill parser 或 artifact_derive
  ↓
research_interpretation
  ↓
ClaimAssessment 或 ClaimRevision
  ↓
research_checkpoint
```

Root Agent 决定何时继续当前 Node、创建新 Node、修订 Claim 或停止研究。Host 只负责边界、持久化和唤醒，不替 Agent 选择科学方法。

## 工作目录

工作区根目录由 Research State 初始化并受 manifest 约束。典型结构为：

```text
workspace/
├─ workspace_manifest.json
├─ research_map/
│  ├─ context.json
│  └─ liveness.json
├─ nodes/<node_id>/
│  ├─ node.json
│  ├─ attempts/<attempt_id>/
│  │  ├─ job.json
│  │  ├─ receipt.json
│  │  ├─ status.json
│  │  └─ outputs/
│  └─ artifacts/
├─ .tspi/artifacts/<artifact_id>/payload
└─ memory/
```

Research Map 中的 Node 是研究语义对象；`nodes/<node_id>/` 是该对象对应的物理工作目录。Job 是 Node 下的一次执行尝试，Artifact 是 Job 输出或后续派生文件。三者通过显式 ID 和 link 关联。

## Monitor

Monitor 不运行第二个 Agent loop，也不解析科学结果。它保存 Job 监视注册、事件、唤醒和通知投递状态：

1. 观察 Job receipt 或远程平台状态。
2. 记录状态变化事件。
3. 对 wake 和 notify 通道做幂等 claim。
4. 将有意义的变化投递给同一 SessionWorker。
5. Agent 被唤醒后自行执行 `job_collect`、Artifact 登记和 Research State 解释。

Monitor 的状态与 Job receipt 分离，避免把通知记录误当成科学事实。

## Host 与 TSPi Agent Server

Host 的职责是：

- 管理 SessionWorker 和 Pi lane。
- 提供认证、路由、租约和恢复。
- 装配核心 Research State、Job Runtime、Artifact 工具。
- 启动 Monitor 唤醒。
- 保存 transcript、session 和 workspace 绑定。

Host 不维护科学 provider catalog，不执行 Claim 判断，也不创建 Compute/Review 子 Agent。TSPi Agent Server 是比“Host”更准确的运行服务名称，但现有安装和连接文档仍可将 Host 作为部署实例名称。

## 扩展边界

扩展只声明 Skill、可选 server 工具和安装配置。科学软件的命令、输入模板和输出解析属于 Skill 内容或 Skill 自带脚本。扩展不再通过 provider registry 向核心注册计算生命周期。

通知扩展可以读取 Research State 的 workspace identity 和 Artifact link，但不依赖报告生成器作为事实来源。报告、图形或导出格式如有需要，应作为独立 Skill helper，从 Artifact 和 Research State 读取数据。

## 测试与质量门槛

当前验证分为：

- Python fast suite：Research State、Artifact Store、Job Runtime、安装和文档契约。
- Node native suite：Agent Server、工具 inventory、workspace mode 和 Pi Harness。
- Skill lint：入口文件、双语 reference 路由和 manifest digest。
- Public surface lint：文档中的公开工具名称。
- Architecture lint：禁止重复 Runtime、provider 和旧包边界。
- Wheel/package checks：Python namespace、source digest 和安装后的自包含性。

所有长时间作业测试必须使用 `/home/iaw/debug/tspi-test-env` 下的环境；测试启动的服务在测试结束时停止并删除。

## 当前公共工具清单

```text
research_read
research_change
research_strategy
research_interpretation
research_checkpoint

job_start
job_status
job_collect
job_cancel
job_probe
job_reconcile

artifact_register
artifact_create
artifact_read
artifact_derive
artifact_link
```

这份清单是 Agent 可见的唯一研究执行协议。Skill 文档可以描述更多领域概念，但不能再引入第二套运行时接口。
