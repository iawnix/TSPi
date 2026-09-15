# TSPi 架构

[English](ARCHITECTURE.md) | [简体中文](ARCHITECTURE.zh-CN.md)

本文介绍 TSPi 如何组织研究会话、运行计算、验证结论，以及向终端、Phone 和 Web 提供结果。
字段定义见实现中的 JSON/TypeBox Schema。

## 系统组成

TSPi 将 Pi 研究会话与科学工具、工作区记录以及终端、Phone、Web 界面连接起来。

```text
终端 / TS Phone
  -> TSPhoneServer（Host）
     -> 每个工作区一个活动 Worker
        -> Pi + Skills + 扩展
           -> Root Agent -> Research Kernel -> 科学记录
           -> Compute / Review -> 工具和日志
           -> Validation Engine + Context Compiler
           -> 分子图像、曲线和报告

TSPi --standalone -> 使用相同研究工具的原生 Pi
TS Web -> 投影提供器 -> 工作区记录和计算历史
```

Root 选择问题、假设、方法、分支、解释和停止条件。Compute 执行选定的计算计划，
Review 在独立会话中评估 Claim。Host 工具实现状态事务、计算、结构操作、渲染和投递。

## 组件与安装

GitHub 安装器构建 TSPi 和选定扩展，完成安装配置，并按选择启用和启动 systemd 服务。

| 组件 | 源码 | 安装后的用途 |
| --- | --- | --- |
| TSPi Agent | `packages/`、`extensions/`、`skills/` | 研究会话和科学工具 |
| TS Web | `components/ts-web/` | 通过 TSPi 投影提供器浏览研究记录 |
| TS Phone | [ts-phone 仓库](https://github.com/iawnix/ts-phone) | 终端与手机共享的 Host，以及 Android 客户端 |

`scripts/install_phone.py` 拉取 Phone 源码、通过 npm 构建服务，并在
`.pi/ts-phone/releases/<commit>/installation.json` 中记录提交、协议和运行文件哈希。
`.pi/ts-phone/current` 选择服务版本。向导在激活前检查服务与所选 TSPi 版本的协议。

套件构建器将 Agent 和可选 Web/Phone 归档组装为 `tspi-package-release/4`。
包含 APK 的 Phone 归档使用 `ts-phone-component-release/2`，包括签名 APK、
源码快照，以及绑定源码、摘要、版本、构建、ABI 和签名者的证明。
Android 客户端安装在手机上。

套件安装器将归档复制到暂存目录，检查清单和摘要，解包组件，准备 Python 运行环境，
然后选择：

```text
<installation>/.pi/packages/tspi/current
```

稳定入口 `TSPi`、`TSWeb`、`TSPhoneServer` 和 `TSPhoneCtl` 解析所选版本。
Phone 入口优先加载套件内的服务，否则加载 `.pi/ts-phone/current` 选择的服务，
并在导入前验证该服务。

配置、模型凭据、SSH 设置、通知设置、Phone token、Pi 会话、工作区和服务状态与
版本文件分开保存，升级时保留。共享 dotenv 读取器依次采用显式环境变量、安装配置
和默认值。

安装、服务管理、升级、回滚和卸载见[安装与运维](INSTALLATION.md)。

## 原生 Pi App Server（实验性）

仓库在 `config/pi-source.json` 中将实验性 Pi server/client 协议固定到提交
`d981de1229ef899957bbe968bc8dcda02a21f477`（`v0.85.1`）。请准备独立的 Pi
源码 checkout，使用 `npm ci --ignore-scripts` 安装依赖并 hydrate 模型数据。
校验 checkout 后，启动安装版本的 server，再连接 Pi client TUI：

```bash
python3 scripts/prepare_pi_source.py --verify /path/to/pi --apply-worker-patch
export TSPI_PI_SOURCE=/path/to/pi

./TSPi --app-server --workspace reaction-a --allow-writes
./TSPi --app-client --connect unix:///path/printed/by/server
```

使用 `TSPI_PI_SOURCE=/path/to/pi npm run test:native-pi` 运行隔离的原生链路检查；
运行工具执行测试时，将 `TS_AGENT_PYTHON` 指向 managed TSPi kernel interpreter。

准备命令会应用 `config/pi-worker-entry.patch`。这是唯一的上游进程入口扩展，
允许服务端选择 `apps/host/pi-session-worker.mjs`。该 Worker 调用 Pi 原生的
`runSessionWorkerWithHarness`，并从 `apps/host/pi-native-tools.mjs` 加载原生 TSPi
`AgentHarnessTool` 定义。`ts_state` 从权威 Research Kernel 提供受限图投影、artifact
查找、能力目录和 change contract 查询；`ts_change` 提交规范状态事务；`ts_remote`
只提供由安装配置约束的只读远端诊断；`ts_seed`、`ts_compare` 和 `ts_import` 直接调用
Compute CLI 并记录确定性 activity journal，`ts_render` 和 `ts_report` 也会把生成输出
绑定到 artifact 与 report journal。`ts_calc` 直接执行 preflight 绑定的固定 Compute
action plan，通过 Harness 持久化进度 checkpoint，并设置 `replay: "never"`，因此 launch
和 cancel 的外部副作用不会被工具 replay 重复执行；不明确的控制结果保持为 `unknown`，
必须依据持久状态进行 reconcile。这些工具不会包装或调用基于 `ExtensionAPI` 的工具及其
child-session runtime。

`ts_review` 使用父级模型创建全新的内存 Pi `AgentHarness`，只开放任务绑定的 result
tool 和可选的一次性 artifact reader。advisory 结果写入既有 Review run journal；
在 Root 通过 `ts_reply` 写入一次性 disposition 之前，Kernel 会继续阻止科学状态变更。
`ts_notify` 使用私有请求文件直接调用 notification CLI；安装配置拥有的收件目标、receipt
幂等性和不明确投递结果的 reconcile 规则仍是权威边界。这三个原生工具都设置
`replay: "never"`。

Unix transport、Chord service、Worker 生命周期和 client TUI 均由 Pi 原生实现；安装
launcher 通过 Harness resources 加载 TSPi `SKILL.md`，并将 App Server 状态保存在
workspace 的 `.pi/app-server/`。这些 session 与 Phone Host、standalone session history
隔离，不会在不同 runtime 之间迁移。未指定 `--allow-writes` 时，Worker 只开放 `read`、
`sys_prompt`、`ts_state` 和 `ts_remote`。指定该标志后，launcher 会先取得 workspace directory guard
和独占 Root lock，再启用完整原生工具集；App Server 进程存活期间会一直持有这些锁。

Worker 使用 Pi Agent Core 加载并格式化 Skill，再把实际生效的 prompt 记录为
`tspi-system-prompt/2` manifest。只读工具 `sys_prompt` 返回完整文本、SHA-256 摘要、
可确认的 contributor 和明确的 provenance 缺口。原生 App Server session 不加载
extension prompt，因此其原生与 Skill contributor 是完整的。

## Python 运行环境

`pyproject.toml` 从 `packages/ts-agent-kernel/ts_agent/` 构建
`ts-agent-kernel`。Agent 构建器在临时源码副本中生成 wheel，放入
`python-dist/`。`ts-agent-release/2` 清单记录名称、版本、大小、SHA-256
和展开后的内容摘要。

运行环境存储分为两层：

| 位置 | 内容 |
| --- | --- |
| `base/<spec-hash>` | 共享的 Conda 科学计算与渲染依赖 |
| `kernels/<payload-hash>` | 使用基础环境并安装所选内核 wheel 的 venv |

`environment.yml` 或 `requirements-runtime.txt` 中的依赖变化时准备新的基础环境。
Conda 先安装其依赖层，再由新基础环境的 Python 安装仅能通过 pip 获取的运行时依赖。
内核变化时准备新的叠加环境。运行环境探测检查模块和
数据文件哈希、基础环境中的 NumPy/RDKit/Matplotlib 来源与 `xyzrender`，以及叠加环境中的
内核分发包。`ts-agent-runtime/3` 清单绑定这些来源和能力。

激活按准备、探测、发布的顺序进行。准备失败时保留当前版本；发布失败时恢复原有清单、
指针、安装状态和稳定链接。已准备的版本保留供重试，服务重启由安装向导或运维人员执行。

## 组件职责

| 组件 | 职责 | 输出 |
| --- | --- | --- |
| 生命周期 Host | 选择版本、初始化工作区、持有写入锁、启动 Pi | 进程和会话身份 |
| Root Agent | 选择并解释研究操作，提交 `ts_change` | 会话和 Decision |
| Research Kernel | 校验并提交科学记录 | 登记表、事务、接受记录 |
| Context Compiler | 选择相关图上下文 | 绑定修订的投影 |
| Validation Engine | 编译和评估 ProofSpec | 冻结检查和 ValidationResult |
| Compute Agent | 执行 Host 绑定的计算计划 | 操作回执和运行结果 |
| Review Agent | 评估 Claim 和选定产物 | 建议和 Root 处置 |
| 确定性工具 | 准备输入、运行计算、分析、渲染、报告、通知 | 产物和运行日志 |
| TS Phone Host | 管理会话并向 Worker 分发消息 | 会话、队列、命令回执 |
| 终端与 Phone 客户端 | 发送消息并显示共享会话 | 交互式会话视图 |
| TS Web | 浏览科学记录和计算历史 | 研究地图、详情和文件预览 |

工作区初始化后，科学变更通过 `ts_change` 和 Kernel 事务校验器提交。
Root 对照源产物核验工具输出后，将其记录为 Observation 或 Finding。

## 科学状态模型

| 记录 | 含义 |
| --- | --- |
| ResearchPhase | 通过标题和目标组织相关研究问题 |
| ResearchNode | 一个研究问题及其交付物、依赖、Claim 范围和结果 |
| Claim | 带假设、反证条件、状态和证据引用的科学陈述 |
| ClaimRelation | 依赖、细化、冲突、替代等具名关系 |
| Observation | 带单位、限定条件和产物来源的不可变类型化科学数值 |
| Finding | 带严重程度和解决状态的异常、限制、冲突或未决问题 |
| ProofSpec | 冻结的声明式验证检查集合 |
| ValidationResult | 针对选定 Observation 的谓词结果和汇总判定 |
| Acceptance | 按接受配置评估 Claim 的不可变记录 |

每个 Node 属于一个 Phase。Node 依赖形成 DAG：一个前驱表示延续，多个前驱支持合并，
依赖较早的检查点支持回溯。已有 Node 和 Attempt 保留历史，Root 根据历史和当前证据
选择下一个问题。

一个 Node 对应一个主要问题和交付物。回答同一问题的重试和参数变化仍是 Attempt；
问题、独立假设分支或主要交付物改变时，创建依赖 Node。假设、前提和反证条件记录在
Claim 中，多个 Node 可以检验同一陈述。

ClaimRelation 形成有向无环图，关系标签描述陈述之间的科学联系。

`ResearchNode.claim_refs` 记录声明范围，`Claim.created_by_node` 记录创建来源。
读取视图使用两者的并集展示 Claim 与 Node 的关系。Research Trajectory 将 Node
与启动、完成时的 Decision 摘要关联，用于上下文、Web 和报告。

Kernel 分配工作区内的可读序号，如 `claim_1`、`rel_1`、`node_1`、`obs_1`、
`fnd_1`、`proof_1`、`result_1` 和 `acc_1`。修订和内容摘要绑定记录版本。
科学类型、标签、关系、概念和验证维度使用开放词汇；执行接口为状态、数据类型和判定
定义枚举。

## 科学记录与运行记录

科学记录共同确定 `workspace_revision`：

```text
workspace.json
research_state.json
phases.json
claims.json
claim_relations.json
research_nodes.json
observations.json
proof_specs.json
validation_results.json
findings.json
acceptances/<acceptance_id>.json
decisions/<decision_id>.json
decision_log.jsonl
transaction_log.jsonl
```

计算 Attempt、Compute/Review 运行、工具活动、报告、远端回执和通知回执构成运行
历史，并参与确定 `operational_revision`。运行 ID 使用 `calc_n`、`sub_n`
和 `op_n`，在锁内按单调递增的高水位分配。

`workspace.operational.calculation_attempt_index()` 校验意图、准备、状态和结果
之间的绑定。Context、API、Web 和文件视图共用其 Attempt 记录与完整性诊断。
父目录无法读取或不满足路径条件时，产生 `scope=attempt_parent` 诊断；遇到符号
链接时记录诊断并停止遍历。

界面显示工作区名称和可读记录 ID。工作区身份、投影 ID、修订和摘要作为追溯记录的
技术详情提供。

## Decision 事务

```text
ts_state -> Root 决策 -> ts_change -> 编译 -> 校验 -> 提交
```

Root 提交带本地别名的有序操作。遇到不熟悉的操作时，
`ts_state mode=change_contract operation=<op>` 从编译器的操作注册表返回字段。

Kernel 分配 ID、解析别名、编译 ProofSpec，并在拟议状态上执行请求的验证。
它持有工作区锁检查完整后状态，提交绑定当前科学修订的 `ts-research-decision/3`。
再次提交完整请求摘要相同的请求时，返回已记录事务。

支持的操作为：

```text
create_phase          create_claim          relate_claims
start_node            complete_node
record_observation    record_finding        resolve_finding
freeze_proof_spec     evaluate_proof
update_claim          accept_claim          set_focus
```

一次 Decision 最多启动一个 Node、完成一个 Node，可以启动并完成同一个 Node。
同时关闭旧 Node 并开启新 Node 时，需要后继依赖。Root 通常在启动当前工作时设置
focus。Focus 记录导航位置，Claim 和验证记录表达科学解释。

## 验证引擎

Claim 收尾使用 ProofSpec、ValidationResult 和 Acceptance：

1. 选择带版本的验证模板，或组合已注册谓词。
2. 冻结检查项、参数、模板摘要和谓词注册表摘要。
3. 针对明确的 Observation 引用和内容摘要执行评估。
4. 检查判定并记录对 Claim 状态的解释。
5. 使用相应接受配置运行 `accept_claim`。

| 判定 | 含义 |
| --- | --- |
| `pass` | 满足声明的检查条件 |
| `fail` | 有效输入未通过一个或多个必需检查 |
| `inconclusive` | 现有有效输入仍无法确定结果 |
| `error` | 声明的检查无法执行 |

接受要求 Claim 状态为 supported，至少有一个 ProofSpec，满足必需维度，覆盖全部
已关联 ProofSpec，采用各自最新通过结果，摘要一致，并已处理适用的阻断 Finding。
接受记录绑定 Claim、配置、验证定义、结果和 Finding。`acceptance_digest`
绑定完整记录；与当前状态比较后确定这份评估是否仍然有效。

对于经典过渡态，驻点、虚频模式和连通性检查分别回答不同问题。电子态、热化学或
稳健性要求取决于 Claim 和接受配置。交叉点与动力学研究可以使用额外维护的模板和谓词。

定义由已注册谓词声明式组合而成。增加新计算或科学检查时，需要维护实现、测试和
更新后的注册表摘要。详细验证说明见[编排 Skill](../skills/tspi-orchestration/SKILL.zh-CN.md)
及相应方法 Skill。

## 上下文编译器

编译器提供绑定修订的投影：

| 模式 | 内容 |
| --- | --- |
| `frontier` | 当前焦点、替代方案、依赖、开放 Finding、未完成验证和近期变化 |
| `claim`、`node`、`finding`、`proof` | 一个对象及其相关邻域 |
| `subgraph` | 调用方选定、具有深度限制的图 |
| `delta` | 自已知科学与运行修订以来的变化 |
| `locate` | 与 ID 或文本查询匹配的当前对象和产物位置 |
| `artifacts` | 已注册逻辑产物和绑定 |
| `capabilities` | 可用计算与验证接口 |

有范围限制的视图提供省略计数和后续读取提示。Claim 产物通过直接 Observation 引用
解析，Attempt 视图区分输入绑定与输出产物。编译器按需重建视图。

紧凑的 `workspace_brief` 包含 Node 轨迹，Web 和报告使用同一轨迹推导。
查询具体验证模板时，会先返回接受的参数和 Observation 选择器，供起草 ProofSpec 使用。

## 只读 Web 投影

TS Web 通过 TSPi 提供器协议读取数据。它的登记表将显示名称映射到工作区来源，
保存在研究工作区外。安装目录发现流程同步 `<installation>/workspaces` 的直接
子目录，保留手工登记，并在发现失败时保留登记表。

一次快照请求规范化工作区并返回修订；发生变化时，同时返回由本次处理生成的 View
和 Graph。浏览器隐藏时暂停轮询，刷新时保留当前选择。

Research Map 按 Phase 和 Claim 组织工作。分组依次采用主要 Claim、唯一派生关联
Claim、未分配分组。连通性 Observation 随其产生 Node 显示，方向使用显式
`connectivity_direction` 限定值。Dependency DAG 展示跨 Phase 依赖、分支、
合并和回溯。

Node 详情包括结论、证据、计算系列、活动、文件和 Decision 历史。Runs 展示目的、
重试与重新计算关系、设置、远端资源、时间和产物。Scientific Conclusions 通过表格
和地图展示 Claim 与 ClaimRelation。

HTTP API 提供读取操作。打开文件预览时，重新核验已纳入 Node 文件视图的文件位置、
普通文件属性、UTF-8 编码和大小。服务运行在回环地址或受信任且配置防火墙的网络中，
网络访问控制由部署环境提供。

安装后的 Web 进程监测稳定 `TSWeb` 入口的目标。新版本和运行环境准备好后，进程
关闭套接字并执行稳定命令，加载该版本。

## TSPi 生命周期

默认 `TSPi` 命令启动 `apps/terminal/index.mjs`，连接经过认证的 Host。
`--phone` 使用同一路径，`--standalone` 启动原生 Pi。启动器通过
`PI_BIN` 或 `PATH` 中第一个 `pi` 选择 Pi。

Host 使用 `workspaceId + sessionId` 定位会话。客户端共享 Worker、事件流和命令
回执。打开历史时读取记录，发送队列请求时激活执行。Host 按工作区串行执行轮次，
并按客户端消息 ID 去重。

原生 Pi 和 Host Worker 使用以下启动流程：

1. 解析安装目录和选定版本。
2. 加载运行环境、远端、通知和缓存配置。
3. 验证隔离 Python 环境和内核内容。
4. 解析工作区并持有会话目录锁。
5. 获取工作区 Root 锁和指定会话的写入锁。
6. 初始化新工作区，或校验已有科学记录。
7. 携带套件 Skill、扩展和主题启动 Pi。

一个工作区同时由一个 Root 写入者持有。不同工作区可以使用各自会话和研究数据并行
运行。共享目录锁与独占会话锁在 Pi 执行期间持续持有。实际持有的操作系统锁确定
归属，锁文件中的 PID 用于描述进程。

Host 管理的 Worker 通过 `extensions/ts-phone-bridge/runtime.mjs` 使用 Pi SDK/RPC。
已保存会话的模型选择优先于启动偏好。凭据和模型注册表位于
`PI_CODING_AGENT_DIR`，默认是 `~/.pi/agent`。模型变更作用于当前会话和后续队列请求。

`--continue` 选择最近会话，`--session-id` 选择指定会话。原生会话的切换或分叉
通过启动器重新打开。ResearchNode 完成时更新工作区，会话可以继续。

## Phone 会话与恢复

Phone Controller 消息与终端消息使用相同的研究工具，Observer 会话使用只读工具集。
Bridge 同时报告模型就绪情况、适合显示的提示错误和连接状态。

队列接收请求时，先持久保存请求及其模型选择，再返回确认。Host 重启后保留等待请求，
将中断的执行标记为 `unknown`。确认未知请求前，检查历史、产物和 Worker 状态。
直接投递回执和事件缓存是有容量限制的内存记录；SSE 重连游标过旧时使用当前快照。

Phone 在 `management.json` 中保存显示名称、偏好和生命周期修订，Pi 保存会话 JSONL。
删除项目或会话前，Host 执行 `--lifecycle-preflight` 并持有 `--lifecycle-guard`。
删除前需要处理活动写入者、远端计算、未决控制操作和完整性错误。

安装记录包含 `tspi-session-guard/1`。Worker 注册时核验子进程 PID、启动身份和
已持有的锁；启动失败返回 `session_writer_active`、
`session_guard_upgrade_required` 等固定错误码。安装器升级时通过工作区锁和进程
检查建立这一约定，执行该升级前应退出已有写入进程。

Host 为每个工作区预留一个启动，收到模型就绪快照后完成激活。退出终端会断开客户端，
`/abort` 停止生成；关闭 Worker 和取消远端计算分别执行。
命令和回执恢复见[终端使用说明](TERMINAL.zh-CN.md)。

## 公开扩展

| 扩展 | 工具和命令 | 用途 |
| --- | --- | --- |
| `ts-workflow-control` | `sys_prompt`、`ts_state`、`ts_change`；`/ts`、`/ts-check` | prompt 检查、研究上下文和状态事务 |
| `ts-workflow-review` | `ts_review`、`ts_reply` | Claim 评审和回复 |
| `ts-workflow-compute` | `ts_calc`、`ts_remote`；`/ts-remote` | 计算生命周期和远端诊断 |
| `ts-workflow-artifacts` | `ts_seed`、`ts_compare`、`ts_import`、`ts_render`、`ts_report`、`ts_notify` | 输入、分析、图像、报告、投递 |
| `ts-workflow-ui` | `/ts-runs` | 活动与运行历史 |

`ts-phone-bridge` 在 Host Worker 和 `--standalone --phone` 中加载。
在传统 Pi extension runtime 中，`sys_prompt` 直接读取 `ctx.getSystemPrompt()` 的最终
prompt，并分别标出 Pi 的结构化原生输入、模型可见 Skill 和 TSPi extension 的精确注入
文本。Pi 不提供逐个 extension 的 prompt delta 或身份，因此无法确认的前序修改及已观察
到的后序修改会标为 `unknown`，`provenance_complete` 保持为 `false`，不会猜测来源。
[Skill 目录](../skills/README.zh-CN.md) 说明方法指导及其使用时机。
工具 Schema 定义调用字段，能力目录描述适配器任务、验证模板、谓词和接受配置。

## 独立 Agent 运行环境

Compute 和 Review 各自在新的内存 Pi 会话中启动，使用选定模型、明确任务范围和工具集。
Host 在本地校验结果，允许一次结构修正，并优先报告供应商错误，再报告输出格式错误。

### Review

Host 准备 Claim 材料，包括相关关系、Node、Observation、Finding、ProofSpec、
ValidationResult 和产物清单。Review 接收这份材料作为上下文。
其工具为 `ts_review_result`，以及选定产物可用时的一次批量
`ts_review_artifact_read`。

Host 检查产物归属、路径范围、大小、摘要和读取预算，记录摘录元数据，并核验结果身份、
范围和引用。Review 成功后，Root 在下一次科学变更前记录一次 `ts_reply`，
再核验采纳建议所需的原始证据。

### Compute

一个 `ts-agent-task/2` 绑定一个 Node、一个不可变意图摘要和一个计划：

```text
launch   prepare -> submit
inspect  status -> optional tail
finalize collect -> parse
cancel   cancel
```

Host 在启动子代理前校验路径、身份、摘要、后端和执行目标。每个无参数操作工具绑定
该请求，并在前置步骤完成后执行一次。提交或取消的效果未知时，需要核对恢复。
模型提供摘要和限制，Host 从操作回执推导结果、产物和恢复标记。

## 确定性工具

### 计算

计算内核实现准备、提交、状态查询、末尾输出读取、收集、取消和解析。
`ts-calculation-intent/7` 绑定 Node、输入产物 ID 和角色、后端/任务/参数、
执行目标和预期输出。重试保持科学意图摘要，重新计算改变该摘要并记录变化字段，
两者都引用同一 Node 内的已有 Attempt。

`local` 目标在 `dry_run=true` 下支持准备和解析。远端执行使用安装级
SSH/Torque 配置。Submit 暂存输入和控制记录，inspect 读取调度器与程序状态。
Finalize 按清单下载声明的输出并在本地解析；队列历史不可用时仍可按清单收集。

### 结构与输入

`ts_seed` 根据一个连通 SMILES 及声明的电荷、多重度生成初始几何。
RDKit ETKDGv3 使用固定随机种子、显式氢、电荷/电子奇偶校验和可选 UFF 初始化，
记录 XYZ 和来源。后续计算用于确定驻点性质。

`ts_import` 接收内联 Gaussian、XYZ 或 xTB 控制输入及安全的语义文件名，
核验元数据、格式与扩展名，返回内容绑定的 Node 产物；同名同内容的重放复用
已有产物，同名不同内容不会覆盖。

`ts_compare` 比较两个已注册 XYZ 产物，支持从零开始的原子映射、反应中心选择、
内坐标、立体化学检查和 RMSD 阈值。JSON 输出记录指标和来源，Root 核验数值后
记录科学 Observation。

### 图像与报告

`ts_render` 使用 `xyzrender` 生成分子 PNG、轨迹 GIF、结构对比图和反应物/
过渡态/产物示意图。`curve`、`energy`、`scan` 和 `convergence` 操作
通过 Matplotlib 将一个 `ts-curve-data/1` JSON 产物渲染为 PNG。
曲线数据记录输入单位、标签和能量参考点。

每次渲染使用所属 Node 下的新输出文件名。`ts_report` 创建新报告包，
校验修订和文件摘要，并复制选定 PNG/GIF 产物及 `asset_index.json`。

### 通知

`ts_notify` 通过 ClawEmail 发送配置的研究事件。安装级
`notifications.toml` 提供收件人和凭据，附件使用经过验证的
`ts-report-package/4` 清单成员。回执标识成功投递；供应商返回未知结果时，
先检查状态再决定下一次投递。

## 运行日志与结果交付

```text
nodes/<node_id>/attempts/<calc_id>/runs/<sub_id>/
reviews/<claim_id>/runs/<sub_id>/
```

Compute 日志属于 Attempt，Review 日志属于 Claim。创建时写入不可变任务和快照，
终止处理时记录操作、结果或失败，以及最终运行状态。进程崩溃可能留下只有任务的
pending/unknown 日志，恢复时检查操作回执和输出。

确定性工具写入带 `node_refs` 的 Activity Journal。共享索引检查归属、路径和
状态/结果一致性，并生成 Node 视图。工具返回将结果交给 Root，`/ts-runs`
读取持久保存的摘要。

完成 Node 前，需要结清所属操作、保持日志一致、处理计算控制记录，并完成收集和解析。
只有意图或已准备的 Attempt，在外部操作发生前可以放弃。之后的状态、结果、控制、
运行或输出记录都需要有效的 `prepared.json` 绑定。

Attempt 的 `failed`、`stopped` 和 `parsed` 状态已结清。
`submitted`、`queued`、`running`、`completed`、`collected`、`missing`
和 `unknown` 需要继续处理后才能完成 Node。科学输入活动失败时，Node 可以按
`inconclusive`、`blocked` 或 `stopped` 收尾。终止的渲染失败保留在历史中，
科学完成情况根据 Node 的证据评估。分析性 Node 可以在没有工具活动时完成。

## 失败处理

| 失败 | 后续处理 |
| --- | --- |
| 操作发生前的字段、绑定或暂存错误 | 修正请求或配置；`retry_same_submission` 允许重试 |
| 提交开始后缺少调度器回复 | 保留作业 ID，核对回执、调度器状态和输出 |
| 程序或解析器错误 | 检查相应输出，并按错误来源记录失败 |
| 科学矛盾 | 记录已核验 Observation 和 Finding，重新评估 Claim |
| 供应商 HTTP/流错误 | 先报告供应商失败，再分类子代理输出缺失 |
| 操作完成后的日志或界面序列化错误 | 保留操作结果，单独报告记录或显示失败 |
| 修订过期、摘要不匹配、图成环或工作区不完整 | 停止事务，检查记录并恢复有效状态 |

详细恢复流程见[程序失败](../skills/tspi-orchestration/references/program_runtime_failures.md)
和[远端执行](../skills/tspi-orchestration/references/remote_contract.md)。

## 实现位置

| 接口或功能 | 位置 |
| --- | --- |
| 工具目录 | `extensions/shared/tool-catalog.ts` |
| 工具请求 Schema | `extensions/ts-workflow-*/index.ts` |
| Agent 任务/结果协议 | `packages/ts-agent-runtime/agent-core/agent-protocol.cjs` |
| 科学记录 Schema | `packages/ts-agent-kernel/ts_agent/workspace/contracts/` |
| Decision 与事务 | `packages/ts-agent-kernel/ts_agent/workspace/decision.py` |
| 状态校验 | `packages/ts-agent-kernel/ts_agent/workspace/validator.py` |
| 事务应用 | `packages/ts-agent-kernel/ts_agent/workspace/engine.py` |
| Attempt 生命周期 | `packages/ts-agent-kernel/ts_agent/workspace/operational.py` |
| 操作字段 | `packages/ts-agent-kernel/ts_agent/workspace/operation_registry.py` |
| 上下文与 Review 快照 | `packages/ts-agent-kernel/ts_agent/workspace/context.py` |
| 验证模板、谓词、配置 | `packages/ts-agent-kernel/ts_agent/validation/` |
| 计算绑定 | `packages/ts-agent-kernel/ts_agent/calculation_contracts.py` |
| 后端与解析器 | `packages/ts-agent-kernel/ts_agent/backends/` |
| 远端执行 | `packages/ts-agent-kernel/ts_agent/remote/` |
| 产物请求 | `packages/ts-agent-runtime/artifacts/request-contract.cjs` |
| 结构分析 | `packages/ts-agent-kernel/ts_agent/structures/` |
| 渲染与曲线 | `packages/ts-agent-kernel/ts_agent/render/` |
| 报告生成 | `packages/ts-agent-kernel/ts_agent/report/` |
| Web 投影提供器 | `packages/ts-agent-kernel/ts_agent/projection/` |
| Web 服务与浏览器 | `components/ts-web/` |
| 终端与 Host 入口 | `apps/terminal/, apps/host/` |
| 安装与运行环境 | `scripts/, pyproject.toml` |
