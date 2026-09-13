# TSPi Package 架构

本文说明 TSPi Package 与 `@iawnix/ts-agent` 的组件归属、状态边界和运行时边界。
字段级调用形状以 JSON/TypeBox schema 为准，任务与合同语义以
`tspi-orchestration` 为准，科学方法和输出交付由专用 Skill 提供。英文原文及完整
字段说明见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 系统形态

```text
安装根目录
  一个选定的 TSPi Package release
    Agent + 选定的 Web / Phone 组件
  TSPi shell shim -> Python 生命周期 Host
    -> 不可变 release、隔离 Python runtime、workspace bootstrap、Root 锁
    -> Pi -> 编排 Skill、专用 Skill、扩展和主题
       -> Root Agent -> Research Kernel
          ResearchPhase + ResearchNode DAG + Claim 图
          Observation / Finding registry、Decision 事务边界
       -> 确定性 Compute / Render / Report / Remote / Notification
       -> Validation Engine、Context Compiler、隔离 Compute / Review Agent
       -> 只读 Activity 与历史投影
```

Root Agent 选择问题、假设、方法、分支、回溯和停止条件。Review 只返回 Claim
中心的建议，Compute 只执行 Host 绑定的 action plan。确定性 Host 工具负责验证、
提交状态和执行明确授权的副作用；子 Agent 不能直接写科学状态，也不能自行选择
路径、文件名或验证结论。

## Package 发布边界

TSPi、`ts-phone` 是独立 Git 仓库，`ts-web` 在 `components/ts-web/` 下保持独立
组件边界。TSPi 拥有 provider、套件组装和安装边界；Phone 产生自己的组件归档，
不决定 TSPi 版本；Web 客户端只消费版本化只读投影。

套件组装器接收可选 Phone manifest，构建 Agent，并校验协议、产物和构建证明，写出
`tspi-package-release/4`。安装器先把调用方归档复制到私有 staging，对同一份字节
完成哈希、检查和解包，再准备并探测 release 绑定的 Python runtime，最后切换一个
`current` 指针。TSPi、TSWeb、TSPhoneCtl、TSPhoneServer 都通过该指针；安装不会
启动服务或安装 Android APK。配置、凭据、workspace、会话和服务状态位于 release 外部。

GitHub 安装向导也可以将 Phone 服务安装为 TSPi 扩展组件。
`scripts/install_phone.py` 拉取源码并构建服务，将提交、协议和运行文件哈希记录在
`.pi/ts-phone/releases/<commit>/installation.json`，通过 `.pi/ts-phone/current`
选择版本。安装器在激活 TSPi 前检查两者的协议兼容性；共享 Phone 入口会验证并加载
所选服务。向导按用户选择配置和启动 systemd 服务，升级时保留配置、凭据和会话。
包含 Android 安装包的组件仍通过 APK 发布构建流程组装。

## Python 分发边界

Pi package 与 Python distribution 是两个协同边界。`build_release.py` 从临时可写副本
构建 `ts-agent-kernel` wheel 并放入 `python-dist/`；Agent manifest 绑定名称、版本、
路径、大小、SHA-256 和 payload digest。`build_package.py` 组装组件，`install_package.py`
是公开安装边界，`install_release.py` 用于 Agent 组件开发验证。

runtime store 分为两层：`base/<spec-hash>` 是共享 Conda 科学环境，
`kernels/<payload-hash>` 是继承该环境的 venv 并承载精确 wheel。依赖变化创建新的
base，内核变化创建新的 overlay。runtime probe 检查模块来源、payload 哈希以及
NumPy/RDKit 的环境来源。激活流程是 prepare、probe、publish；失败时旧的 current、
manifest 和稳定链接保持原状。

## 权威矩阵

| 组件 | 使用模型 | 写入规范科学状态 | 外部作用 | 持久输出 |
| --- | --- | --- | --- | --- |
| 生命周期 Host | 否 | 仅 bootstrap | 启动 Pi | release/config、身份、Root 锁 |
| Root Agent | 是 | 仅通过 `ts_change` | 选择受限工具 | 会话与 Decision |
| Research Kernel | 否 | 唯一写入者 | 无 | registry、acceptance、事务 |
| Context Compiler | 否 | 否 | 无 | revision 绑定投影 |
| Validation Engine | 否 | 通过 Kernel apply | 无 | ProofSpec、ValidationResult |
| Review Agent | 是 | 否 | 无 | task、snapshot、建议或失败 |
| Compute Agent | 是 | 否 | 仅绑定 typed tools | task、action、结果或失败 |
| Compute / Render / Report | 否 | 否 | 确定性本地或远程作用 | manifest、产物、报告 |
| Web / Phone / UI | 否 | 否 | 只读投影 | 瞬时界面或 UI registry |

除 bootstrap 外，只有 `ts_change` 可以修改规范科学状态。扩展、Review 结果、parser、
scheduler、renderer、report builder、通知和 UI 都不能绕过该边界。

## 科学状态模型

### Claim 图

Claim 是带 statement、assumptions、falsifiers、tags、status 以及 Observation/
validation history 的科学陈述。ClaimRelation 连接两个 Claim，关系类型保持开放，
但有向图必须无环。Claim 和关系 ID 是 workspace 内单调 ordinal，只表示身份；Node
声明范围与 Claim 创建来源共同形成只读邻域。

### ResearchPhase 路线图

Phase 是用于导航的标题、目标、创建 Decision 和时间戳记录。每个 Node 属于一个
Phase；Phase 不拥有状态、后继规则、方法政策、验证政策或权限含义。

### ResearchNode DAG

Node 是有边界、可审计的研究决策事件，包含 Phase、目标、主要交付物、依赖 Node、
相关 Claim、Observation、Finding、ProofSpec、ValidationResult 和 artifact 根。依赖
形成 DAG，用于继续、合并和回溯；DAG 记录谱系但不决定下一步。一次 Decision 最多
启动一个 Node 并完成一个 Node；改变目标或主要交付物应创建后继 Node。

### Observation 与 Finding

Observation 不可变，绑定 concept、subject、typed value、unit、qualifier、摘要、
产物 ID/digest、producer、Node 和 Decision。Finding 表示异常、限制、冲突或未解决
问题，可引用 Claim、Node、Observation；开放的 blocking Finding 会阻止相关 Claim
被 acceptance。

### Validation 与 acceptance

ProofSpec 是冻结的声明式检查集合，绑定目标 Claim、dimension、模板和 predicate
registry digest。ValidationResult 记录选定 Observation 的 digest、每个 predicate
结果和聚合 verdict：`pass`、`fail`、`inconclusive`、`error`。

Acceptance 是独立的不可变评估快照。Acceptance profile 检查 Claim 状态、ProofSpec
覆盖、每个 specification 的最新通过结果、digest 和 blocking Finding；历史记录保留，
当前性由它与当前规范状态的比较推导。ProofSpec、ValidationResult 和 Acceptance
共同表达收尾验证。

Claim 类型、关系、Node 标签、Finding 类型、validation dimension、Observation concept
和 subject 保持开放字符串；只有确定性执行合同使用封闭枚举。

## 规范与运行状态

规范状态包括 `workspace.json`、Phase/Claim/Node registry、Observation、ProofSpec、
ValidationResult、Finding、acceptance、Decision 以及 decision/transaction log。这些
记录共同确定 `workspace_revision`，只能通过 Kernel 事务修改。

运行或派生状态包括 Attempt、Compute/Review runs、Node outputs、activities、reports、
Pi 会话、锁、remote receipt 和 notification receipt。它们可以有自己的
`operational_revision`，但不能改变规范科学记录。`calc_n`、`sub_n`、`op_n` 是 workspace
范围的单调 operational ID。

## Decision 事务

```text
ts_state -> Root decision -> ts_change（编译、校验、加锁、应用）
```

Kernel 私下分配技术 ID、解析 alias、编译 ProofSpec、在隔离副本校验完整后状态，
绑定当前 scientific revision，并一次性提交 `ts-research-decision/3`。重放只有在完整
request digest 相同时才幂等。支持创建 Phase/Claim/Node、关联 Claim、记录
Observation/Finding、冻结和评估 ProofSpec、更新 Claim、accept Claim、设置 focus。

## Validation Engine

```text
模板 + typed parameters
  -> compiler 展开 checks
  -> 带 template / registry digest 的冻结 ProofSpec
  -> registry 调用维护中的确定性 predicate
  -> 带 Observation digest 的 ValidationResult
  -> acceptance profile 生成不可变 assessment snapshot
```

Root 只能选择已注册模板或声明式 predicate 组合；定义中不能包含 Python、shell、
import、表达式或可执行插件。新增科学行为必须进入维护代码、测试和新的 registry digest。

## Context Compiler 与只读 Web 投影

Context Compiler 向模型提供 revision 绑定的有界图投影，而不是原始 canonical 文件。
`frontier`、`claim`、`node`、`finding`、`proof`、`subgraph` 和 `delta` 模式都报告省略
计数和检索提示。投影按需重建，不写索引，也不改变 scientific/operational revision。

`ts_web` 是外部只读 explorer，不是第二个 workflow runtime。它从 canonical state 和
运行投影重建视图；registry 位于 workspace 外部，provider 负责私有路径和 workspace
校验。浏览器端只能通过版本化 provider protocol 读取。

## TSPi 生命周期与扩展

Host 解析安装、校验 release、绑定私有环境和 Root 锁，然后启动 Pi。workspace bootstrap
接受当前合同，生命周期操作在同一目录锁下执行。安装、升级、runtime publish、launcher
切换和 current 指针切换采用可回滚的 prepare/probe/publish 流程。

扩展通过稳定 Pi API 注册工具、命令和 entry renderer。Review runtime 接收紧凑的 Claim
snapshot，输出建议、限制和依据；Compute runtime 接收 Host 绑定的 action plan，只能调用
允许的 typed tools。两者的结果、失败和日志由 Host 从确定性 action 记录派生。

## 确定性工具平面

Compute kernel 负责 intent、控制记录、SSH/Torque 调度、输入和输出解析。`ts_seed`、
`ts_compare`、`ts_import` 负责受限的结构生成、比较和内容寻址导入。`ts_render` 负责
分子、结构、曲线、能量、扫描和收敛图的确定性渲染；`ts_report` 构建绑定 revision 和
文件 digest 的报告包。`ts_remote` 只读检查远程基础设施；`ts_notify` 向固定目标发送
digest 绑定的通知。

## Journal、结果交付与失败语义

每个 Compute/Review run 都有不可变 task packet、action/result/failure journal 和
digest。结果先作为操作记录保存；Root 校验主要产物并通过 Decision 提升为 Observation。
报告、Activity、Context、API 和 Web 使用同一套派生索引。

错误按边界返回结构化 code、message、retryable 和相关 ID。解析、验证、权限、digest、
锁和安装错误停止当前事务；远程不确定作用保留 receipt 和诊断信息。升级错误保留旧
release 和 current 指针，供诊断或重试。

## 合同位置

- `contracts/`：Phone、Web、Package 和协议 schema。
- `packages/ts-agent-kernel/ts_agent/`：Research Kernel、workspace、validation、compute、render、report。
- `packages/ts-agent-runtime/`：Agent、Compute、Review 隔离运行时。
- `components/ts-web/`：Web provider、server、静态界面和组件发布边界。
- `extensions/`：Pi 扩展与 Phone bridge。
- `scripts/`：构建、安装、runtime 和稳定兼容入口。
- `skills/`：公开编排、科学方法和输出 Skill。
- `tests/`：合同、集成、发布和运行时验证。
