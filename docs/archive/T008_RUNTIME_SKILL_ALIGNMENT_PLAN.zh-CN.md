# t008 后续修复方案：Conda 环境、Skill 编排与唯一状态协议

> Historical archive / 历史归档：本文记录旧设计或一次性验证，不是当前接口合同，也不代表本次重构已通过验收。当前设计见 [Research Memory plan](../RESEARCH_MEMORY_DESIGN_AND_IMPLEMENTATION_PLAN.zh-CN.md)。

日期：2026-10-07（北京时间）。状态：已实施并完成安装验收；最终落地范围及实测结果见同目录 T008_RUNTIME_SKILL_ALIGNMENT_VALIDATION.zh-CN.md。

## 1. 目标与已确认问题

保持现有架构：领域 Skill 拥有算法、命令构造、解析和科学验证；Job Runtime 执行通用任务；Research State 拥有研究状态；Monitor 观察任务变化并请求唤醒；Host/Agent Server 管理会话与输入队列。

t008 暴露的问题包括：

- email 的正确路径已出现在 Skill 目录中，Agent 仍猜测错误路径；guard 返回泛化的包源码访问错误，没有给出定位恢复信息。
- Agent 没运行 email 配置检查就断言缺少收件人，并把独立计算一并置为等待用户。
- 普通 job_probe 结果被不必要地提升为 FactFinding；四次错误引用导致整个 ChangeSet 原子拒绝，包括同批节点更新。
- 当前 Skill 请求生成器自己解析 job.toml。远程 Python 没有明确绑定，环境解析与 Runtime 曾不一致。
- core orchestration 的 references/runtime_boundaries.md 仍描述旧 capability catalog、launch/inspect/finalize、Monitor 收集输出和旧 artifact_derive 语义，与当前代码不一致。
- 当前 State 把 user_input_required 投影为 lifecycle=decision_needed；调用方必须同时解释 disposition。checkpoint 投影也会清除 ready_node_ids。不能让各消费者继续各自补条件。
- 先前真实 Worker 测试由模型桩预设正确调用，仅验证工具链，不覆盖真实 Agent 自主编排。

已执行的环境命名调整：安装配置只有 local、remote，cluster_1w 兼容入口已移除。历史记录不改写。

## 2. 各层职责与唯一写入者

| 对象或决策 | 权威与唯一写入边界 | 其他层如何使用 |
| --- | --- | --- |
| 软件位置、Conda 环境绑定 | 安装配置 job.toml；安装工具负责创建/验证 | Skill 与 Runtime 读取同一规范化配置 |
| 方法、参数、科学校验 | 领域 Skill 指导 Agent | Runtime 不按化学方法进行 dispatch |
| 下一项研究工作、证据是否值得记录 | orchestration Skill 指导 Agent | 通过现有研究工具提交决策 |
| Claim、Node、依赖、策略、阻塞、checkpoint | Research State | Host、Monitor、Skill 读取返回状态 |
| 研究 liveness 与 memory 索引 | Research State 的可重建投影 | 不接受第二套人工或 Skill 写入 |
| Job/进程/调度器状态与原始输出 | Job Runtime | State 通过现有桥接映射为 Attempt；Agent 解释结果 |
| Artifact 文件与来源 | 现有 Artifact Store / Evidence Registry 接口 | FactFinding 引用实际注册 ID |
| 观察事件、投递租约与去重 | Monitor outbox | 事件不能直接改变科学结论或规划下一计算 |
| 会话输入、执行中回合、工具准入 | Host / Agent Runtime | 读取 State 的准入结果；不重算研究决策 |
| 会话记忆 | Pi 会话存储 | 帮助恢复对话，不能覆盖 Research State |

Job 状态、会话状态和研究状态服务不同对象，可以并存；不能让它们分别保存一份互相竞争的“研究下一步”。core Skill 是公开协议的使用说明，不是第二个调度器或状态机。

## 3. 远程 Conda 与 job.toml

### 3.1 环境布局

采用按依赖集合隔离的、版本化的 Conda prefix：

- runner 环境：Python 及普通包装脚本依赖，供 xTB/Gaussian 的输入生成和结果解析。
- CF22D 环境：Python、NumPy、PySCF、geomeTRIC、pyscf-dispersion，以及经过验证的 CF22D 实现依赖。
- 其他 Skill 若有冲突依赖，可声明另一个环境，不为每次 Job 创建环境。

xTB/Gaussian 可执行程序保留各自软件安装，包装脚本环境不代替这些程序。生产环境候选位置为远程 /home/agent/soft/tspi/envs/<environment>-<lock-digest>；需先检查实际 Conda 路径、共享文件系统及计算节点可见性。不能因为 PySCF 的 Python 恰好可用就隐式借用它运行所有脚本。

测试安装和环境遵循 AGENTS.md：置于 /home/iaw/debug/tspi-test-env。远程测试需先验证该测试根可用；不可用时先明确测试目录约束，不偷偷把测试安装混入生产软件目录。

### 3.2 配置方案

以下为拟新增结构，当前版本不能直接使用。Python 绑定统一为结构化对象；不并行维护 python 字符串、conda_prefix 和另一套优先级配置。

```toml
[environments.remote]
kind = "remote"
ssh_host = "agent.1w"
scheduler = "torque"
remote_root = "/home/agent/1w-data2/ts-remote-workspaces"

[environments.remote.python]
manager = "conda"
conda_executable = "<verified-remote-conda-absolute-path>"
prefix = "/home/agent/soft/tspi/envs/runner-<lock-digest>"
lock_ref = "<packaged-runner-lock-resource>"

[environments.remote.backends.xtb]
command = ["/home/agent/soft/xtb/current/bin/xtb"]
# 包装脚本继承 environments.remote.python。

[environments.remote.backends.gaussian]
command = ["g16"]
activation_script = "/home/agent/soft/gaussian/activate_gaussian16.sh"

[environments.remote.backends.pyscf.python]
manager = "conda"
conda_executable = "<verified-remote-conda-absolute-path>"
prefix = "/home/agent/soft/tspi/envs/cf22d-<lock-digest>"
lock_ref = "<packaged-cf22d-lock-resource>"
```

唯一选择规则：backend.python 存在时使用它，否则使用 environment.python。配置同时声明旧解释器命令和新 Python 绑定且存在歧义时，安装校验报错；迁移工具一次性转换，而不是运行时猜测优先级。CF22D 的旧 command=Python 在迁移后不再成为第二个解释器来源。

新增字段必须同步进入安装配置校验、公共 schema、规范化配置读取与 Skill helper。helper 使用同一解析器生成普通 Job argv；保持 Job Runtime 的通用 command/inputs/outputs 接口，不新增科学 capability 或第二种提交协议。公共解析器需作为已注册资源或稳定公共接口提供，Skill 不导入被禁止读取的私有包实现。

运行方式默认采用经过实际 PBS 验证的 `conda run --no-capture-output -p <prefix> python ...`。软件 activation_script 与 Conda 的组合顺序固定，验证最终解释器及程序解析路径。清理宿主 PYTHONHOME/PYTHONPATH、禁用用户 site-packages，防止 Host 环境泄漏进远程科学环境。

### 3.3 创建、升级与诊断

环境创建属于安装/维护工具：读取锁定依赖，在新 prefix 创建并校验后才切换配置。失败保留旧绑定，不就地改动正在使用的环境，不在普通研究回合中临时 pip install。

Skill 提供依赖要求和资源摘要；安装过程保存解析后的 lock、平台信息和环境指纹。job.toml 保存目标机器绑定并引用锁文件，避免把依赖版本在 Skill、job.toml、安装器里抄三份。

诊断分层：配置语法 → SSH/调度器 → Conda prefix/Python → 计算节点导入 → 科学方法最小检查。登录节点上的 Python --version 不能替代计算节点验证。Job 回执记录实际解释器、配置摘要、环境锁摘要和 Skill 资源摘要，保证重启后能追溯运行环境。

## 4. core Skill 编排与证据政策

orchestration 决定下一步，research-state Skill 解释如何合法读写。两者引用统一公共契约，不能分别定义 disposition、工具阶段或状态迁移。

普通 probe 的成功输出默认留在会话/运行记录，不要求创建 FactFinding。只有需要跨回合引用、解释阻塞或支持研究判断时，才通过现有 Artifact 工具保存并登记原始观测，再引用返回的 ID。不能用 `job_probe:local`、工具调用 ID 或自然语言冒充 Artifact ID。

修正此前“自动登记所有 probe 为证据”的倾向：本轮优先补齐按需登记流程，不增加新的 observation 数据库、强制研究事实或每次探测的研究 revision。

错误恢复应返回稳定 code、失败字段、允许的引用类型和下一步工具，例如 evidence_reference_unknown → research_read(mode=evidence) 查找或 artifact_create/register 登记 → 重试需要证据的 Finding。保留原子事务和事实来源校验。

低价值观测记录失败，不应该让独立准备工作停下。若失败的是执行必需的策略、权限、真实输入 Artifact 或 canonical 状态写入，仍必须先修复前置条件。将可独立提交的节点推进与可选诊断记录分开，避免可选 Finding 导致整批关键更新回滚。

对方法 × 资源矩阵建立可独立推进的节点，交付节点依赖报告；某个环境失败只阻塞依赖它的工作。email 先运行无发送配置检查，再判断是否缺少收件人；缺少收件人不能反向成为优化任务的依赖。

## 5. 唯一生命周期与唤醒规则

### 5.1 统一 State 的判断输出

在 Research State 内集中解释 checkpoint、Node 依赖、Attempt 状态和作用范围。由同一份规则产生 liveness、可执行节点、阻塞节点以及事件准入结果。Host 和 Monitor 消费结果，不再分别解释 decision_needed + disposition 的组合。

兼容读取旧状态仅放在 State 边界，规范化后返回明确语义；Skill 文档不再要求理解历史投影组合。若调整公开字段，必须更新同一契约及所有消费者，不能新旧双写、双判定。

### 5.2 结束当前回合与下一次唤醒分开

- 存在独立可执行工作：Agent 继续执行；确需分回合时使用现有 continue_required，并由 Host 按持久化、去重、预算受限的规则处理。它不等于 Monitor 定时轮询计划。
- 仅剩已提交的外部任务：waiting_external 必须引用真实 Attempt；Job 状态发生有意义变化后由 Monitor 发事件。
- 用户输入确为必要条件：记录具体问题、影响节点及依赖；不将不依赖该输入的节点冻结。
- 外部任务与用户等待共存：State 判断事件影响范围。相关独立任务完成事件仍可入队，用户等待节点保持阻塞；不能用全局 user_input_required 一刀切丢弃全部事件。
- 缺少 checkpoint 的有限补救仍由 Harness 负责；已有有效用户等待不触发循环补救。

Monitor 只写观测事件、outbox 和投递状态，不写 Claim/Finding、不发邮件、不选择方法，也不自动收集并解释科学结果。Agent 被唤醒后通过 job_status/collect/reconcile 与 Artifact 工具处理结果。

同一 event_id/request_id 的投递需幂等。暂不准入是 deferred delivery，不当成新失败无限唤醒；事件应保留至允许处理或经权威规则确认过期。不得把已拒绝的 wake 标成成功投递。

### 5.3 防止再出现双协议

- 清理全部 core Skill 引用链中的退役能力目录、旧 launch/inspect/finalize 和旧 artifact_derive 执行语义。
- 工具名、参数、disposition 与错误码从唯一公共 schema 导出参考；Skill 只维护语义指导与合法例子。
- 中英文 Skill 和引用做一致性检查，例子针对实际公开接口执行。
- 同一 State fixture 驱动 State 校验、Host 准入、Monitor 事件处理和 Skill 示例测试，防止各层各自维护期望。
- Memory 投影可从 canonical State 重建；不增加 Skill 自己的 workflow.json、待办状态库或 next_run 调度表。

## 6. 实施顺序与验收

1. 固化公共契约与职责边界，清理 core Skill 的旧协议引用；补路径错误的准确诊断和正确 Skill 位置。
2. 实现 Conda 配置解析与安装校验，迁移 job.toml，构建隔离环境并验证计算节点运行；请求生成器共用解析规则。
3. 改造编排的按需证据登记和可操作错误恢复；验证普通 probe 不产生必须写入的 Finding。
4. 集中 State 准入规则，覆盖独立节点、混合等待和事件去重；Host/Monitor 只消费权威结果。
5. 安装包集成测试通过后，开展真实模型行为评测及科学最小任务，再发布安装。

验收至少覆盖：

- local/remote 名称一致；请求生成、提交和回执使用同一目标。
- 远程计算节点使用配置的 Conda prefix，包装脚本和 CF22D 依赖分别隔离；缺失环境产生明确诊断。
- 普通 probe 后可继续准备/提交；需要 FactFinding 时只能引用已登记证据，错误能够按提示恢复。
- 邮箱已配置时不重复询问地址；未配置时只阻塞交付，其他独立计算继续。
- 一个计算节点失败不阻塞其他节点；计算完成并不自动变成科学结论。
- 等待用户与外部任务共存时，合法事件不丢失；重复事件、Host 重启及 outbox 重投不产生重复计算或邮件。
- 模型桩测试验证机制；真实模型从原始自然语言请求独立完成 Skill 选择和流程推进，不能预设正确工具序列冒充行为验收。
- 邮件完整链路在隔离传输下测试 prepare/send/status、附件一致性和收据去重；实际发送遵循用户授权。
- 不存在两份可独立修改的研究 liveness、memory 或 workflow authority。

测试产物和环境全部按 AGENTS.md 放置；测试结束停止并删除测试服务与任务。本文不宣称任何新科学计算或实际邮件投递已完成。
