# 架构收敛与执行可靠性整改

状态：实施中。基线：a7422028。目标覆盖 2026-10-09 外部审查及 t001 的需求登记失败。
完成必须逐项提供代码、行为和安装验证证据；局部测试通过不能代表整体完成。

## 所有权

| 模块 | 权威职责 |
| --- | --- |
| Host/网关/连接 | 身份、连接、工作区与会话访问、请求转交 |
| Pi Harness/Worker | 输入准入、排队、中断、持久 submission、模型和工具调用 |
| Research State | 用户要求、研究状态、证据绑定、评估、交付范围 |
| Job Runtime | 请求准备、环境绑定、提交恢复取消、结果收集 |
| 领域扩展 | 科学输入输出、方法执行、验证和研究指导 |
| Skill | 方法选择和结果解释；引用实际执行入口 |

跨模块允许不同协议，禁止同一事实的多个权威实现。保留模型/凭据配置；本次部署使用全新工作区和会话，不实现旧格式迁移或兼容恢复。当前协议的运行中任务、中断恢复和副作用去重仍是必要能力。

## 实施清单与验收

### P0 错误入口

- [x] P0.1 删除无鉴权 server.mjs、旧直连 Pi HTTP 网关及专用测试/发行入口，修正文档。
- [x] P0.2 保留的浏览器网关统一身份、Host/Origin/内容类型校验、方法白名单和唯一请求格式。
- [x] P0.3 外部输入不能声明内部 producer；稳定业务身份由共同准入路径处理。
- [x] P0.4 中断原子绑定目标运行，迟到请求不能中断下一轮。
- [x] P0.5 停止接受 email v1 新发送；历史 sent/unknown 保留且不会重发。

### P1 基础契约

- [ ] P1.1 单一扩展发现/验证清单，支持包外扩展及版本身份；JS/Python 使用相同快照。
- [x] P1.2 单一 job.toml 安装/运行契约及生成 schema；清除无消费者字段与隐式目标。
- [x] P1.3 工具/decision 参数由规范契约提供，移除自别名、空 mode filter、旧调用适配。
- [ ] P1.4 State 单一受管 Python bridge 和解释器配置；移除逐调用旁路与内嵌 worker 字符串。
- [x] P1.5 单一工作区初始化与目录查询；Web/Host 共用，单工作区访问不遍历全部研究状态。
- [ ] P1.6 唯一 workspace ID 语法、Host 方法名/cursor/模型字段；规范配置边界和安装布局。

### P2 执行与恢复

- [ ] P2.1 终端/手机/内部事件共享 Worker 准入；Pi submission 作为消息接收权威，清除重叠回执。
- [x] P2.2 固定 Pi 版本的精确 view/task/submission 适配，移除兼容猜测与伪造 fault/operation 字段。
- [ ] P2.3 结构化 Monitor/continuation；单一事件交付，读取投影不驱动研究。
- [x] P2.4 Python I/O 移出 Pi 事务；版本绑定、短事务入队及消费前复核保证竞态恢复。
- [x] P2.5 声明式执行入口通用准备器，移除三后端硬编码；允许显式环境绑定的临时脚本。
- [x] P2.6 Job 输入形式仅解析一次；准备脚本不写 State，受管入口登记准备引用。
- [x] P2.7 结构生成/科学验证获得 Job/Attempt 和环境来源；短任务允许同步收集。
- [x] P2.8 验证器使用目标 binding，不将 Host Python 默认提交远端；声明入口依赖需求。
- [ ] P2.9 执行身份绑定相关输入/参数/脚本/环境锁；无关配置更改不改变身份；执行前核验。
- [ ] P2.10 本地 Job 脱离 Host cgroup，最小环境、资源与 scratch；Host 重启任务可恢复。
- [ ] P2.11 远端科学预检与资源规则、传输超时明确；原生程序不强制无用 Python 环境。

### P3 研究模型和 Skills

- [x] P3.1 requirement 独立登记；缺 profile/能力保留未解决事项，空列表不代表实际任务成功。
- [x] P3.2 profile 为可选模板；任务可组合检查，复用 Runtime/validator/Agent evidence assessment。
- [ ] P3.3 科学计算履行必须关联实际执行；机器失败不能自评覆盖；原始要求不可偷偷弱化。
- [x] P3.4 requirement 与 Gate 共用检查机制、不同作用域；普通 Node 不强制 Gate/exemption。
- [x] P3.5 Claim 用于实际科学判断，Plan 用于策略，不要求简单任务填形式化对象才能执行。
- [x] P3.6 明确 runner 结果字段、单位、spin/multiplicity；共享科学格式处理与资源描述。
- [ ] P3.7 核心 Skills 保持领域中立；协议规则唯一来源，删除模板重复和 lint 填充文字。
- [ ] P3.8 能力声明与执行入口一致；IRC 可复用 Gaussian，CREST/QBICS/NEB 明确支持边界。

### P4 清理与发行

- [x] P4.1 删除无写入方 activity journal、identity、测试专用工厂、未消费 provider metadata。
- [ ] P4.2 删除重复依赖字段、旧 tool-result、空 backend/mode flags、拒绝专用入口和旧配置产物。
- [x] P4.3 删除旧事务、工作区、会话和目录迁移器及安装迁移分支，只支持当前协议；保留当前任务的事务恢复与副作用去重。
- [ ] P4.4 必要 Pi patches 精确登记（包括 008、009），每个补丁具行为验证；不保留猜版本兼容层。
- [ ] P4.5 发行清单、wheel、技能资源、文档、类型、源码检查一致；防退化规则只有规范定义。
- [ ] P4.6 提交推送并升级安装，配置/凭据哈希一致，使用全新工作区和会话；记录部署版本与验证。

## 整体验收（必须实际完成）

- [ ] V1 包外测试扩展由两语言一致发现并执行、验证；新增扩展不修改核心。
- [ ] V2 t001 真实模型与真实三方法 opt/SP，坐标依赖正确；隔离接收端验证交付。
- [ ] V3 t009 映射/鞍点/IRC 证据链，错误、缺失、过期证据不会被弱 Gate 或报告绕过。
- [ ] V4 并发终端/手机/Monitor、重复输入、丢响应、断连、重启、迟到中断。
- [ ] V5 正式服务约束下本地计算及 Host 重启恢复；配置远端执行路径的实际验证。
- [ ] V6 重装保留配置与凭据，使用全新工作区/会话；当前协议下未完成要求仍未完成，未知副作用不重试。

测试环境及产物放在 /home/iaw/debug/tspi-test-env；测试服务结束即停止删除。生产邮件不作为测试。

## 证据记录

- P0：保留网关的 HTTP 行为测试、真实 Pi Harness 定向中断、Host 来源验证已通过；email 13 项单元测试通过，包含 v1 拒绝、历史 sent/unknown/sending 协调与并发重试。内部服务共同准入仍需 P2 验证，所以 P0.3 暂不勾选。
- P1 进行中：Python 消费 Node 校验的扩展清单；Worker 通过私有 JSONL 初始化传入同一快照。验证器 ID 与版本共同定位；State 工具复用会话 bridge。44 项需求/验证器/证据测试通过。尚未完成完整 Native、类型及发行验证。
- P1 补充：真实 Worker 已验证包外扩展 profile 经相同快照被 Python 查询；工作区/bridge/Worker 12 项通过，类型检查通过。清单消费者移入 tspi_foundation，架构检查通过；独立命令每次重新验证资源，避免同路径变更复用旧清单。
- P3：需求、Gate、执行及输入证据回归 56 项通过，涵盖缺模板、任务自定义检查、机器失败不可覆盖、同一次执行成功且完整收集、未暂存输入拒绝、输入和结果版本绑定。State/恢复回归 64 项通过，原有科学路径验证仍通过。简单真实 Job 可不创建 Claim、Gate 或 StrategyPlan。原始自然语言的提取完整性仍是 Agent 判断，代码不声称能证明。
- 扩大单元/契约回归曾出现 2 项失败：规范 schema 错误码变化和远端配置测试缺少必填字段；均已修正并通过对应回归。完整 Node/Python、安装和 V1–V6 仍待完成，当前未提交或部署。

- P1/P4 补充：工具工厂直接使用 Durable 的 `(params, api, context)`，Worker 只有一个策略/结果边界；checkpoint 使用同一闭合 schema 并检查版本，废除 turn/checkpoint 别名。真实 Worker/bridge 25 项、工具边界 17 项已通过。
- 工作区目录改为 Python 单一实现，Host/Backend 共用常驻通道，Monitor 与 Web 共用目录；直接 lookup 不扫描兄弟目录，列表不读取 ResearchMap，attachment 才完整验证。目录/Web/安装器回归 77 项通过。旧 Web 登记迁移已按用户要求撤销。
- Node 只保留带 condition 的 dependencies，删除 completion_exemption、旧结果/错误/能力/通知/artifact 协议空壳。旧数据转换路线已撤销，仅使用当前协议的 dependencies。相关 Python 回归 139 项、Host/Worker 11 项通过。
- P2 下一步仍是共同 Worker 准入：Pi submission 负责持久状态；来源与内容摘要在同一个 Pi 事务中绑定。Monitor 的 State 读取必须移出事务，并在实际消费前复核。当前这些项尚未完成。

- P2 输入链已接入真实 Worker：终端与 Host 共享 admission，Pi submission 是唯一输入状态；持久来源与内容摘要同事务绑定，内部服务认证后才接收结构化事件。删除 session-control 协议、输入回执状态机和 scheduler lease；Host 其它变更的 RPC 回执、Job/邮件回执保留各自职责。
- P2 复核：State/Python 检查移出 Pi 事务，消费依据绑定 submission，跨 GenerationTask 与重启保留。Monitor 消费前仍保持 pending，被 State 否决时保留事件及原身份；符合条件后才允许新输入。Host 不再读取 liveness.json，Worker 通过受管 bridge 返回 State outbox。
- 验证：完整 Native 207 项通过，Monitor/Pi patch Python 11 项通过，类型、架构、术语及发行清单检查通过（454 文件）。全新 Pi pin 已实测 001–009 全组应用与重复应用；009 登记 Native 输入身份。真实 Worker 续跑/Job/Monitor/重启场景使用隔离模型端点，无生产邮件。
- 遗留会话边界：无来源证明的历史 pending 输入在 Worker 恢复前明确拒绝，保留其 Pi 状态，禁止靠 ID 前缀补造来源。历史迁移已移出范围；完整并发验收仍未完成，P2.1/P2.3、P4.3 与 V4 暂不勾选。t001 备份只读核对显示其旧输入已 done，无 requestId；没有改写该记录。

- P2.6：删除 JS 准备文件解析器；Runtime 仅解析一次，摘要及覆盖校验、State 准入之后，将准备引用与 Attempt/dispatch intent 同事务登记。准备命令仅输出文件和摘要。39 项准备/恢复/可靠性回归及真实 Worker 文件提交—续跑—Monitor—收集—重启测试通过；包括提交事务中断、重复请求不重跑及准备后文件被改写。
- P2.5 进行中：扩展清单新增 executors，声明 Skill、backend、runtime、entry、纯 CLI 契约、argv 模板、输入角色及输出；统一准备器为 tspi_runtime.executors，删除化学三后端准备脚本。资源复用已验证 Skill 清单，Python 再核对 Worker 快照摘要。仓库外原生执行入口无需 Python 绑定即可执行和收集；选定绑定以外的配置变化不改变 work_id。45 项 Python 回归和 44 项扩展加载测试通过。临时脚本显式绑定、运行前环境核验及结构生成/验证器迁移仍待完成。
- P2.5 后续：临时脚本通过同一准备器的 --script/--backend 路径固定代码与依赖，使用明确的目标 Python；实际 Job 执行与收集通过。验证器也从声明的 backend 解析目标 Python/资源/队列；远端默认环境不再接收 Host sys.executable。86 项绑定/需求/科学路径/可靠性回归通过。
- P2.7 进行中：chemical.resolve/inspect/seed/reaction、path-candidates/path-irc 和 cf22d-doctor 已声明执行入口，Skill 示例改为准备后 job_start。结构生成和验证器均记录选定绑定；通用收集支持显式 recursive 输出目录，所有生成文件注册同一次 Attempt，已暂存 Artifact 的来源传播到派生输出。75 项回归包含真实 RDKit 种子/QST2 候选生成；Gaussian 仍使用合成输出。尚需去除 Host 科学依赖、目标依赖声明、真实环境核验与安装验收，不能据此关闭 P2.7/P2.8 或 V2/V3/V5。
- 阶段回归：Native 207 项、Python 单元/契约 351 项、类型、Skill 检查和发行清单 455 文件均通过。
- P2.10 进行中：应用配置创建的本地平台统一通过 systemd 用户 transient service 启动 supervisor；显式清空继承环境，CPUQuota/MemoryMax 约束资源，Job 内创建专属 scratch 并支持绑定环境的 {scratch}。34 项回归包含真实受限父服务停止后 Job 独立存活与恢复、模拟凭据/PYTHONPATH 不继承、资源值核对、scratch 路径及测试服务自动移除。尚待真实 Host 安装/升级与求解器端到端验收，P2.10/V5 暂不勾选。
- 后续完整回归：Python 单元/契约 353 项、Native 207 项通过。移除仅报错的旧 bridge/import RPC 分支和 Host main、测试中的无效 Native 写入开关、ASE-NEB Pixi 产物及过时计算模型页面；科学运维文档改为当前声明入口/Job 路径。清理后的 Host/权限回归 15 项、发行清单 451 文件与术语检查通过。测试单元和 test-env cwd 进程均已核对为空。

## 下一阶段的明确边界

1. 科学目标环境发行：本地结构/验证、三种求解器、渲染及离线重装已实际验证，环境锁和安装路径已提供。仍需正式安装服务和升级验收，不能用独立 Runtime 验收代替真实模型 t001 或部署验证。
2. 远端科学验收：本地/远端资源、环境、scratch 和传输规则已对齐，现有 Torque 目标的原生执行与回收已实测；仍需在发布的科学环境上验证实际求解器。Host 最小控制环境和原生远端任务通过，不能因此宣称科学能力全部就绪。
3. 当前协议与恢复：只支持当前工作区和会话，不做历史输入、事务或目录迁移。Host v2 单一 cursor/方法名/模型字段与当前安装布局完成后，继续完整并发/断连和真实安装验收；当前版本 pending 输入与 Job 的恢复必须保持。
4. 科学语义与 Skills 收尾：结果字段、多重度、共享 XYZ 和核心资源固定已完成并验证；仍需完成核心协议说明去重和整体验收，尤其是真实 t009 的科学证据链。
5. 完成真实 V1–V6 与发行安装验证后，再提交推送、升级，并核对配置/凭据摘要，使用全新工作区与会话。当前没有提交、推送或部署。

## 目标环境核验实施记录

- 执行入口和验证器新增声明式 `requirements`（Python 版本、包版本约束、实际导入模块）。本地和 SSH 目标通过同一通用探针核对解释器前缀、显式 Conda 锁、pip 固定版本、安装回执、包清单，以及程序/激活文件摘要。原生入口无需 Python。
- 准备请求包含环境观测并参与 work_id；新提交重新核验，执行开始时再次检查。Python 检查程序暂存且固定摘要，激活文件先校验再加载。Runtime 检查入口身份、固定参数、资源和输出声明，不能把正确的环境摘要用于另一个程序或脚本。
- 慢环境探测、扩展发现及验证器准备移出 State 锁。短事务再次检查配置、准入和验证器输入版本；已存在的提交先返回原回执，环境漂移不会触发重跑。执行指纹使用实际展开后的 outputs。
- 删除化学扩展 `_shared/execution_bindings.py` 的三后端安装白名单。安装器先通过公共扩展清单进行静态检查，在受管环境与扩展安装后执行通用 readiness 检查。新安装回执包含 inventory_sha256；旧回执需要显式 --adopt 并实际核验，不能手工补造。未显式 adopt 时不接受既有清单漂移。
- 回归暴露并修复本地平台按 job_id 缓存终态造成跨目录同名 Job 复用旧成功结果的问题；持久状态文件成为终态来源。Native 测试入口显式传递所选测试 Python，避免落回环境中的 python3。
- 验证证据：完整 Python 单元/契约 370 项通过（convergence-env-source-final.log）；最后的探针超时清理、SSH 命令、回执和安装器回归 96 项通过（convergence-env-targeted-final.log）；Native 207 项通过（convergence-env-native-fixed.log）。类型、架构、Skills、术语、git diff 检查通过，发行清单 454 文件通过。日志均在 /home/iaw/debug/tspi-test-env。测试 systemd 单元已核对为空。
- 这些验证使用真实子进程、隔离 Python 前缀、测试 Conda 清单和 SSH 传输替身；尚未代表实际 Conda 科学安装、真实集群或正式安装服务验收。P2.8/P2.9/P2.11 暂不关闭。
- 后续重点转为科学目标环境锁与实际安装、移除 Host 科学依赖、对齐远端资源/scratch/环境规则；其后仍需科学结果字段与 Skills 收尾及 V1–V6。当前未提交、推送或部署，生产模型配置、凭据和 t001 未更改。

## 控制环境与测试环境分离记录

- Host wheel 的直接依赖仅保留 jsonschema 和 packaging；控制探针只验证 JSON Schema、版本约束及安装 payload 来源，更新为 tspi-runtime-probe/4。实际最小 Conda 环境包含 34 个包，不含 RDKit、NumPy、ASE、SciPy、Matplotlib、xyzrender 或 pytest。
- Host 安装器改为消费带 SHA-256 的 environment.lock.txt，安装及修复不再重新求解 YAML。删除空置的 requirements-runtime.txt 和对应 pip 安装路径。基础环境摘要覆盖 YAML 与显式锁；kernel overlay 身份同时绑定基础环境及 Python payload，环境锁变化不会复用旧 overlay。
- 科学测试依赖和原科学锁移入 tools/test/environment.{yml,lock.txt}；开发及测试入口使用独立 test-base 前缀。wheel 测试产物和结果记录默认落在测试根目录。安装摘要只报告实际控制探针和逐执行入口的目标核验结果，不再无条件宣称渲染就绪。
- 完整 wheel 测试暴露并修正两处安装边界问题：Python bootstrap 与 Worker 的包根变量统一为 TSPI_PACKAGE_ROOT，扩展发现使用同一根解析器；源码根标记改为当前 extensions/core/skills 路径。修正测试目标遗漏基础环境依赖，以及 operation catalog 测试中遗漏已有策略/解释操作的旧预期。
- 验证：146 项定向安装/启动/发行清单回归通过（convergence-host-targeted-final.log）；完整 wheel Python 套件 610 项通过（convergence-host-source-fixed.log）；Native 207 项通过（convergence-host-native.log）。发行清单检查 453 文件通过，架构、公共术语及 git diff 检查通过。日志位于 /home/iaw/debug/tspi-test-env。
- 实际安装证据：convergence-control-install-final.json 记录最小控制基座复用与新 overlay 安装；convergence-control-install/final-acceptance.json 验证无科学库时扩展发现、陌生领域要求登记及未满足状态保留、失败结果的报告整理。该验证未调用模型或发送邮件，不能替代科学目标及 V1–V6 验收。
- 测试服务及 test-env cwd 进程已清理。尚未提交、推送或部署；生产模型配置、凭据和当前 t001 证据未修改。

## 远端执行与资源规则实施记录

- submission 仅在准备/提交边界按目标、后端、显式请求合并一次。平台适配器只校验实际值；Attempt 和执行指纹使用合并后的资源。已准备请求不接受新增或覆盖队列/资源字段，既有提交重试仍返回原身份。安装器与 Runtime 共用同一契约，JSON schema 由其生成；拒绝本地队列、Torque select、PBS select 与 cpus/memory_mb 混用和零 walltime。
- 本地 supervisor 与远端 wrapper 共用最小环境、线程默认值、scratch 规则及较短执行时限。SSH 控制与 rsync 传输分开计时，超时清理传输进程组。远端目录按实际本地 Job 路径隔离；保存真实目录后再调度，响应丢失从 scheduler.id 恢复而不重投。历史目录仅用于原任务恢复。
- 远端回收排除 spec、receipt、status 和其他控制文件，不能用计算目录中的文件覆盖本地执行事实。程序自行退出 124 与实际执行超时分别记录。调度器自动邮件、自动重跑关闭；qdel 的成功回执只证明取消请求被接受，须观察到调度器终态/明确记录消失才记录 cancelled，连接故障保持 unknown，竞争中先完成的程序保留原退出结果。
- 验证：56 项初步定向回归通过；完整 wheel 回归发现一处旧 Monitor 测试对本地任务使用队列参数，已改用远端提交夹具。64 项定向复查通过；加入异步取消恢复验证后，最终完整 wheel Python 套件 631 项通过（convergence-remote-wheel-final.log），Native 207 项通过（convergence-remote-native.log）。发行清单 454 文件、架构、公共术语、schema 一致性及 git diff 检查通过。
- 真实 Torque 验收：隔离的包外原生执行入口通过通用准备器与实际 Job dispatch 提交，不配置远端 Python。batch 任务 209914 因当前无符合条件的空闲节点而未运行，主动取消并核实调度器 C 状态，收集结果如实保留不完整。新身份的 fat 任务 209915 成功执行、完整收集，同一 Attempt 登记 3 个 Artifact；验证线程数、scratch、输入/输出内容及 native 无 Python 绑定。证据在 /home/iaw/debug/tspi-test-env/convergence-remote-live-fat/acceptance.json，两个隔离远端根目录均已删除，cleanup.json 留存终态核对。
- 这证明真实 SSH/调度器/原生环境检查/执行/回收路径，不代表科学求解器及远端 Python 环境已经通过。P2.11/V5 和完整 V1–V6 继续保持未完成；科学锁与安装、Host 协议与科学语义收尾仍需推进。没有提交、推送或部署。


## 本地科学环境和结果语义验收

- 发布 `extensions/chemical/environments/` 的 wrapper、structure/validation、CF22D、render Conda 显式锁及带哈希的渲染 pip 依赖。实际安装了五个前缀（含 render 离线重装），与发行锁及安装回执逐一相符，离线与在线渲染清单一致。CF22D 使用通用 x86_64 构建，无自定义 LD_PRELOAD。wrapper 支持 glibc >=2.17，科学锁要求 >=2.28；旧集群的科学环境仍需单独验证。
- 最小控制 Python 不含 RDKit/NumPy/PySCF/xyzrender。它通过实际环境绑定完成 RDKit 结构生成、CF22D/xTB/Gaussian opt-sp、映射验证和 SVG/PNG 渲染。统一 readiness 对全部配置的 16 个 executor/validator 及 wrapper 绑定返回 verified。证据：`convergence-science-install/readiness.json`、`environment-audit.json`；离线安装日志为 `convergence-science-offline-install.log`。
- 三种 runner 统一生成 `science-result/2`：`checks_passed` 仅表示 runner 数值/输出检查；`scientific_validation` 保持 not_assessed。删除含义不一致的 validated 和显式 Gaussian 的重复执行成功字段，Job 回执持有执行状态。Gaussian 保留原始 program_returncode；CF22D 的 `pyscf-run/2` 用 imaginary_frequency_count_matches 明确只比较虚频数量。报告输出 `science-report/2`，不将历史 validated 转为新验收。
- 公开 runner 参数统一为 --multiplicity（2S+1），进入 PySCF/xTB 时才转换内部自旋参数。共享严格 XYZ 读取器校验元素、有限坐标、帧选择、轨迹原子顺序及 XYZ 电子数奇偶关系。删除两个重复 xyz.py 和无执行入口的 xtb_scan.py；验证器暂存同一个共享读取器。
- 原始科学日志原先没有完整登记为 Artifact，现由 executor 声明递归结果收集并保留必需输出检查；CF22D 临时 scratch 不作为结果保留。实测三种 opt-sp 收集 9/19/12 个 Artifact，全部字节摘要和 producer Attempt 核验通过，每种 SP 均使用对应优化坐标。CF22D 另实际完成 opt_freq，得到水分子的三个频率、零虚频；科学结论仍保持未评估。证据：`convergence-science-semantics-live/acceptance-audit.json` 及同目录的原始回执、收集记录。
- 映射验证器在实际 structure 环境中处理正确与错误映射，Job 均成功执行，而科学 verdict 分别为 pass/fail，并进入持久结果回执。渲染结果的输入摘要、SVG/PNG 文件及收集结果已核验。这不代表真实 TS/IRC 或模型驱动 t009 验收。
- 核心 Skills 新增 manifest，入口、双语文档与引用资源同领域扩展一起校验摘要；配置包外扩展也保留核心清单校验。Worker 移除未校验的核心目录旁路。资源更新脚本覆盖文档和代码，三个计算 Skill 删除模板重复并引用共同结果契约。清除 core 的 /compute、CREST 的 --check-remote 和架构文档中未实现的 provider 元数据说明。
- 验证：最终完整 wheel Python 647 项通过（`convergence-semantics-wheel-final.log`），Native 208 项通过（`convergence-semantics-native-final.log`）。随后 CF22D 内部字段收敛通过 38 项定向回归及真实 opt_freq。类型、架构、公开术语、18 个 Skill 契约和 9 个变更 Skill 的 quick_validate 通过；发行清单 471 文件通过。测试日志及产物均位于 `/home/iaw/debug/tspi-test-env`。
- 完整回归前出现的文档标题/链接失效和新递归输出漏填 min_bytes 已修正。重复验收请求曾被实际执行指纹拒绝，没有重复发起旧任务；保留拒绝证据并使用独立计算验收范围。
- 当前没有提交、推送或部署。生产模型配置、凭据及 t001 未修改。P2.7/P2.8/P3.6 按上述实现与行为证据完成；V1–V6、Host 协议字段及最终升级仍未完成。
- 清理核验：测试 systemd Job/父服务单元为空，`/proc` 中 cwd 位于测试根目录的进程为空；记录在 `convergence-science-semantics-live/cleanup.json`。最终 CF22D opt_freq 的实际暂存资源摘要与当前源码一致。

## 当前协议收敛与安装维护边界

- 方向纠正：上一轮加入的旧事务、工作区和输入来源迁移不符合用户已明确的“不保留工作区/会话历史”，全部撤销。此前迁移测试记录不作为当前方案的验收证据。
- 安装维护仅保留串行安装、停止写入进程和启动就绪检查；禁止自动回滚的边界改为“服务已经启动”，防止抹除新版本已接受的事实。
- Host 只接受 tspi-host/2 显式握手；能力名和调用方法统一用斜杠，cursor 只接受完整 epoch/sequence，模型选择统一为 model: {provider, id}。终端创建与恢复共用该字段，移除多余的二次 model/select。Host 独占事件序号与缓存，删除 Backend 的重复重放缓存；不同 epoch 返回当前快照。
- 删除 session_file/version/format/runtime_kind/read_only 等旧 backend 标记、可空 backend 守卫、两种安装路径识别、Web 的旧 .pi/ts-web 路径猜测，以及 SQLite bootstrap 拒绝专用函数。doctor 不再解析旧 SQLite/JSON 数据，只检查当前数据并报告不支持的旧存储。
- Foundation protocol.json 为 Host 版本、workspace ID 和退休存储文件名提供跨语言定义；JS/Python/CJS 直接消费，公开 schema 由契约测试校验一致。删除无运行消费者的 workspace.schema.json、workspace_identity.schema.json。
- 验证：完整 wheel Python 653 项通过（convergence-protocol-verified-wheel.log）；最终 Web 目录修改后 20 项定向 wheel 回归通过（convergence-protocol-web-wheel.log）。Native 213 项通过（convergence-protocol-final-native.log），终端模型参数修复后 5 项定向回归通过（convergence-protocol-terminal.log）。类型、架构、公开术语、diff 检查及 470 文件发行清单通过。
- 测试根目录为 /home/iaw/debug/tspi-test-env；convergence-protocol-cleanup.json 确认测试服务与工作目录位于该测试根的进程均为空。
- 整体整改仍未结束：Phone v2 客户端匹配、真实安装/科学环境验收、核心 Skill 收尾及 V1–V6 中未完成项继续保留。本次未提交、推送或部署，生产配置与凭据未修改。

## Research State turn 协议移除

- 删除专用 `research.turn` bridge 方法及 `research_turn_request/result` schema；Research State 不再实现通用 turn start/orient/end/wake RPC 或 turn audit/idempotency log。`research_checkpoint` 只记录 disposition，Native Worker 根据同一份 liveness 投影判断是否需要有界 follow-up。
- Monitor 事件保留只读 `research.monitor_assess(event_id, session_id)`：在 workspace 锁内核对 workspace/session、Attempt、Node、解释/收集状态和 disposition。Pi submission 仍是输入状态权威；Host 在准入和首次消费前评估事件。
- 更新 Research State command catalog、bridge v2 声明、Monitor 测试及英中文 ADR/ResearchMap 文档；清理旧 schema 包。Node 测试不再假设 `execute_command("research.turn")` 会因 bridge 方法无效而失败，只检查 bridge API 没有 `turn()`，command catalog 也不再定义该命令。
- 验证：Monitor Python 定向测试 10 项、Research State bridge/command Node 测试 11 项、删包相关 Python 契约测试 8 项、完整 Native 测试集 220 项、TypeScript 检查、架构边界检查、公开术语检查和 `git diff --check` 均通过。日志位于 `/home/iaw/debug/tspi-test-env/monitor-assessment-protocol-*`。
- 源码 bridge 测试进程已退出；进程检查发现 6 个更早启动、由测试安装下 `0.18.0` release 派生的 bridge worker，启动时间为 2026-10-08 19:32–19:33，未由本轮测试创建，未停止或删除。未启动服务、未触碰正式安装。
- 此项不代表整体验收完成：真实模型 t001、真实 t009 证据链、并发/断连验收、正式安装及 V1–V6 仍按各自状态保留；未提交、推送或部署。
