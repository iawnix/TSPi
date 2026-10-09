# t006 暴露问题的修复与完善方案

> Historical archive / 历史归档：本文记录旧设计或一次性验证，不是当前接口合同，也不代表本次重构已通过验收。当前设计见 [Research Memory plan](../RESEARCH_MEMORY_DESIGN_AND_IMPLEMENTATION_PLAN.zh-CN.md)。

> Historical design record. Research graph and lifecycle guidance is superseded by the [current notebook architecture](../ARCHITECTURE.md).

日期：2026-10-06。状态：t006 核心执行链路的源码修复已实施；本地真实计算与自动化测试已通过，远程完整计算及部署后 Agent 端到端验收尚未完成。详见 [修复验收记录](T006_REPAIR_VALIDATION.zh-CN.md)。

本文保留修复前的证据基线与完整设计；下文“当前”“尚未迁移”等描述对应审查时点，不代表实施后的源码状态。实际完成范围、未完成项及测试清理以验收记录为准。

补充审查：已确认科学执行代码在删除旧 Provider 栈时一并消失，未迁入当前 Skill。修复首要交付调整为“审查并迁回领域脚本及测试”，见 2.4、3.6、3.7；不能仅增强 Skill 文本或 Agent 路由。

## 1. 架构结论与范围

保持当前方向：**Agent 依据 Skill 设计任务，Skill 提供领域知识、脚本、输入模板和验证规则，Job Runtime 提供通用、持久的执行能力，Research State 保存研究事实与证据。邮件同样由 email Skill 实现。**

此前把 `createChemicalToolFactories()` 返回空数组、chemical manifest 的 `providers: []` 解释为缺少计算入口，是错误判断。这些是旧接口或旧 manifest 合同的残留，不能据此恢复化学 Provider、Capability 注册表或 `calculation_*` 工具。需要清理残留，而不是重新填充。

Job Runtime 可以支持科学任务。它相较于一次性 Bash 调用的价值是任务身份、隔离目录、输入输出留存、远程调度、超时取消、重启恢复和结果收集；科学方法及结果是否可信由 Skill 和 Agent 负责。Bash 可以是 Job 的命令，两者并不排斥。

本文包含：科学 Skill 执行规范、通用执行可靠性、Agent 生命周期、研究状态与证据、后台唤醒、email Skill 迁移、旧协议清理、测试及 t006 恢复。本文不部署新版本、不重跑 t006、不取消历史远程任务，也不发送邮件。

### 1.1 目标职责

| 层 | 应承担的职责 | 边界 |
| --- | --- | --- |
| Agent | 理解目标、读取 Skill、形成计划、调用工具、解释证据、决定下一步 | 不临时替换方法，不把进程成功当作研究完成 |
| 科学 Skill | 方法选择规则、配置使用、环境检查、输入生成、工作流、解析和科学验证 | 脚本可执行，但不直接修改 canonical Research State |
| email Skill | 生成邮件请求、附件核验、调用 SMTP/邮件客户端、回执与去重 | 用户授权范围内发送；不依赖 Host 通知 Provider |
| Job Runtime | 执行 argv、本地/远程平台、日志、退出码、产物检查、持久状态 | 不理解 CF22D、xTB、Gaussian、能量或邮件正文 |
| Research State / Artifact | Node、Attempt、输入输出、Finding、证据关系的持久关联 | 通过统一事务入口写入，不允许脚本直接改状态文件 |
| Host / Monitor | 会话运行、通用 Job 监测、持久唤醒 | 不选择科学方法，不直接决定或发送研究邮件 |

## 2. 证据基线与根因

必须区分历史执行、当前源码和拟议改造。t006 使用的安装版本是 `0.17.0-sha256-04ba38a602ee9b8c`；当前工作树已有未提交的 Skill、Runtime、生命周期及文档改动，不能把它们视为当时执行过的版本，也不能默认已修好。

### 2.1 可核查的历史材料

- 工作区：`/home/iaw/ResearchAgent/workspaces/t006`。
- 会话：`/home/iaw/ResearchAgent/.pi/app-server-host/sessions/t006/f020d09a-6e94-4667-9aff-f4641ede6bcf/session.sqlite`。
- Job 输入及回执：工作区内 `runs/jobs/<jobId>/spec.json`、`receipt.json`、日志及 `operations/jobs/`。
- 研究状态：`research_map/context.json`；检查点：`checkpoints/`。
- 安装配置：`/home/iaw/ResearchAgent/.pi/job.toml`。修复只记录必要的配置摘要，不复制凭据。

### 2.2 已确认的问题

| 现象与证据 | 根因判断 | 修复归属 |
| --- | --- | --- |
| 当前源码与 t006 安装包的 chemical 扩展均只有 70 个 Markdown 和一个 manifest；历史 runner、解析器及相关测试已删除 | 去除旧执行协议时没有完成领域实现向 Skill 的迁移，Agent 缺少可直接复用的执行材料 | Skill 资源迁移 + 发布验收 |
| Agent 已读取有关 Skill，仍临时拼接简化脚本 | 不能归结为没有发现 Skill；读取后的执行约束、参考材料一致性及脚本复用不足 | Skill + Agent |
| 本地 CF22D 日志 `ModuleNotFoundError: No module named 'pyscf'` | 使用裸 `python`，没有落实安装配置指定的解释器与激活环境 | Skill 环境准备 |
| 同一 Job 记录退出 0、成功 | `python ... \| tee ...` 返回了 tee 的状态，掩盖计算程序失败 | Skill 脚本；Runtime 保真与产物检查 |
| 标为 CF22D 的脚本两次调用 `scf.RHF` | 科学方法实现错误；即使程序跑通也不是请求的 CF22D | CF22D Skill |
| CF22D 写 `result.txt`，声明输出却为 `calc_cf22d_local/result.txt` | 工作目录与输出路径不一致 | Skill + Job 路径合同 |
| 本地 xTB/Gaussian 仅通过当前 PATH 检测，返回 127 | 把未激活环境误判为软件未安装；已存在配置的安装位置 | Skill 环境检查 |
| xTB/Gaussian 脚本只有优化及 grep 最后能量 | 缺少明确的优化后单点步骤及收敛核验；grep 不能证明完整工作流 | 方法 Skill |
| 方法级探测被 `research_decision_required` 拦截 | 探测计划与研究决策/执行门禁未衔接，平台探测也不代表方法可用 | Agent + 生命周期 |
| `research_change` 被 execute 阶段拒绝 | 多 Job 执行中解释结果、记录问题和继续执行的阶段转换不完整 | 生命周期 |
| `waiting_external` 引用 Job ID 被判为未知 Attempt | Job 没有关联已登记的 Attempt；不能靠伪造引用绕过 | Runtime 适配层 + Research State |
| 六个 Job 的 `attempt_id` 均为空；最终研究状态无 Attempt、Artifact、Finding、Evidence Link | 执行回执与研究状态之间缺少完整持久关联 | 状态与证据集成 |

已知本地结果没有形成有效科学能量；远程结果没有收集到可核验的终态证据。不能把本地失败推断为远程全部失败。

### 2.3 不确定项与额外发现

- 历史远程回执的 `running` 不足以区分排队、运行、挂起。三次提交对应调度器 ID 为 `209763.cluster.hpc`（xTB）、`209764.cluster.hpc`（CF22D）、`209765.cluster.hpc`（Gaussian）。
- 此前审查时 SSH 连接被拒绝，只能说明当次无法核查远程，不能反推为原始失败原因。本文没有再次连接或改变远程任务。
- 本地 PySCF 环境可导入、xTB 可启动版本检查，并不等于 CF22D 方法实现、优化依赖和 Gaussian 完整计算已经验收。
- t006 没有完成报告或发送完成邮件；没有证据表明 SMTP 导致计算失败。邮件 Provider 是本次一并解决的架构不一致。
- 当前 `artifact_link` 适配代码仅返回关系对象；`artifact_derive` 保存的是派生描述，不能等同于已持久关联证据或实际执行了分析。
- 当前 Monitor worker 引用不存在的 `apps/agent-cli/monitor.py`。这说明不能宣称后台自动恢复已经可用；尚不能据此断言它造成了 t006 的全部等待问题。
- 当前 manifest、打包入口和部分架构文档仍有旧 Provider 设计。特别是 `COMPUTE_MATRIX_AND_SCRIPT_PLAN.zh-CN.md` 和 `ARCHITECTURE_BOUNDARIES.md`，需要随实现同步改写。

### 2.4 补充确认：领域实现随旧协议被删除

当前 `extensions/chemical/` 与 t006 所用 release 的同名目录均为 **71 个文件：70 个 .md、一个 manifest.json**，没有 Python、Shell 脚本或独立输入模板。不是只在某个 Skill 搜索路径中没有找到脚本；源码与安装包的该扩展都缺少这些执行资源。

Git 提交 `3db94107548f17b0d7bdffbd056bf27feafe5edc`（`remove legacy scientific provider execution stack`）删除旧 Provider 注册和调度代码时，还删除了：

- `chemical_runtime/backends/pyscf_runner.py` 与 `chemical_runtime/pyscf/runner.py`：CLI、CF22D 方法构建、优化/SCF、结果输出及收敛证据。
- `chemical_runtime/backends/xtb.py`：参数生成、所需产物、程序终止和 SCC 收敛解析；以及 `xtb_scan.py`。
- `chemical_runtime/backends/gaussian.py`：XYZ 读取、Gaussian 输入构建及输出解析。
- CREST、ASE NEB、结构比较、反应映射和热化学等其他领域模块。
- `test_pyscf_backend.py`、`test_xtb_crest_backend.py`、`test_scientific_analysis.py` 等相关行为测试。

这些文件当时位于 `extensions/chemical/providers/` 下，**其目录归属不能证明其中所有内容都是可删除的协议代码**。例如历史 CF22D runner 实际通过 DFT 构建方法、检查 CF22D/D3 可用性、读取优化收敛事实；t006 临时脚本却使用 RHF。历史实现仍需针对当前依赖重新验证，但已有的科学处理逻辑明显比临时拼接的脚本完整。

另一提交 `8f9ec8793a472a2c8fb5fd265c2416dd35b35e4f` 删除了 report/render Skill 及其 builder/renderer。报告与绘图能力也应列入迁移盘点；本次先恢复 t006 所需的结构化汇总和报告，其他能力明确列为后续项目，不声称已经保留。

目前未在当前 Python 源码中找到上述 PySCF runner、xTB prepare/parse 等实现的同名迁移版本。打包清单已有 `extensions/chemical/skills/**`，所以现有证据首先指向**源码迁移不完整**，不能简单归咎为打包漏了几个文件。后续仍需验证完整发布包的资源包含情况。

由此修正因果判断：去掉旧协议 → 领域实现未迁入 Skill → Agent 依据文字临时重建执行细节 → 方法、环境、解析与失败处理退化 → Runtime/状态缺陷进一步使失败难以识别和恢复。脚本缺失是已确认的结构性缺口，与 t006 的错误直接相关；其对每项失败的独立贡献仍应通过修复后的对照运行验证。

## 3. 科学 Skill 与 Agent 的修复

### 3.1 从“读说明”落实到可复用执行材料

执行类 Skill 应作为可交付的资源包：操作说明 + 可执行脚本/明确可用的外部 CLI + 输入模板 + 解析验证 + 依赖声明。研究策略、机理推理等纯知识 Skill 仍可只有文本，不要求每个 Skill 都机械增加脚本。

每个方法 Skill 提供可直接使用的脚本/模板、环境检查及结果验证器。优先从 Git 历史审查和迁回现有领域实现，复用已验证的外部 runner；缺少适配当前版本的部分再补齐。目录及脚本命名可以沿用现有布局，不新增 Host capability 注册。

Skill 入口必须明确：

1. 哪些请求适用，必须读取哪些 reference，以及已支持的程序版本。
2. 从哪里读取安装配置，怎样激活环境，怎样取得实际 executable。
3. 输入如何生成，运行目录如何设置，哪些文件必须作为 Job 输入保存。
4. 优化与单点的依赖关系、结果解析器及失败条件。
5. 哪些结果可以登记为证据，失败后允许哪些恢复操作。

Agent 的执行流程应要求在提交前形成任务记录：方法、基组、环境、步骤、输入 digest、Skill/脚本版本、预期产物、依赖和资源设置。该记录是 Skill 工作产物及研究计划的一部分，不是重新引入 capability descriptor。

清理 reference 内仍引用 TSPi adapter、descriptor、实时注册 workflow 等旧表述。第三方 runner 自身的真实 API 可以保留，并明确其与 TSPi 工具的区别。中英文入口及关联 reference 同步更新，避免 Agent 从旧文档重新走回旧协议。

### 3.2 环境准备和分级探测

采用三级检查，并分别保存结果：

| 检查层次 | 负责方 | 验证内容 |
| --- | --- | --- |
| 平台可达 | `job_probe` | 本地目录可用，或 SSH/调度器可访问 |
| 程序可启动 | Skill 提供的小型检查 Job | 激活环境后实际解释器/程序路径、版本、依赖、必要动态库 |
| 方法可执行 | 方法 Skill 提供的最小检查 | 方法实现可加载、优化依赖可用、输入语法及结果验证器可用 |

平台探测不能宣称“CF22D 已就绪”。方法检查继续通过通用 `job_start` 执行，不扩展出 `probe_cf22d` 等工具。检查必须有资源与时间上限；昂贵检查应进入研究计划。

本地使用配置所指向的 `/home/iaw/soft/...` 环境。例如 PySCF 应落实到配置的 Python 和激活脚本，不能默认系统 Python；远程使用远程安装配置，不能复制本地绝对路径。

允许配置在激活后使用 `g16` 等命令名；校验的是**激活后的有效程序**，不是一律禁止裸命令。绝对可执行文件路径也不替代动态库、scratch 和程序环境的准备。避免在 Agent 上下文或日志中输出完整环境变量。

Job Runtime 只读取平台配置而不自动套用化学 backend，并不天然是缺陷。由 Skill 读取相关配置并生成 argv/环境；有重复代码时提取普通配置辅助模块，不加入方法选择或领域 dispatch。

Agent 应先完成支持这些探测的最小研究决策和 Node 绑定。门禁报错需返回可操作的缺失字段/下一步，不允许反复提交相同请求，也不以关闭全局研究决策门禁解决。

### 3.3 正确表达 t006 任务矩阵

目标是 `3 方法 × 2 环境 × 2 步骤 = 12 个逻辑计算步骤`：

| 方法 | 优化 | 优化后单点 | 关键验证 |
| --- | --- | --- | --- |
| CF22D/6-31G** | 已验证的 CF22D runner + 几何优化器 | 同方法、基组，在该次优化几何上显式求能 | CF22D 实现确实加载，不能用 RHF 替代；SCF 与优化收敛 |
| GFN2-xTB | 显式 GFN2 优化 | 使用 `xtbopt.xyz` 等经过验证的最终几何显式单点 | 两步均为 GFN2，结构有效、优化收敛、能量有限 |
| M062X/6-31G** | Gaussian 对应 Opt 输入 | 读取优化结构或正确 checkpoint 的独立 SP 步骤 | 方法/基组正确，两步正常结束，优化收敛，SP 属于最终结构 |

每个环境分别完成自己的 opt → SP 依赖，不能用本地优化结果冒充远程优化结果。默认分为 12 个计算 Job 便于恢复；若 runner 能完整记录两个步骤，也允许六个组合 Job。探测、解析、报告及邮件 Job 不计入这 12 个科学步骤。

水分子记录 charge=0、PySCF spin=0 / multiplicity=1、坐标单位、原子顺序、基组与收敛参数。原始输入和最终几何分别保存，SP 输入绑定优化输出 digest。

不静默降级方法、不更换基组、不把优化最后一次 SCF 当作已完成用户指定的 SP。优化收敛也不等于已通过频率证明极小值；用户没有要求频率时不追加该结论。

### 3.4 结果格式和验证

Skill 脚本输出结构化结果，至少包括实际方法/基组、程序版本、输入 digest、步骤、能量及单位、几何及单位、SCF/优化收敛事实、验证结论及原始日志定位。明确输出 schema 和 parser 版本，避免只保留一个 `result.txt` 数字。

结果验证器应检查方法身份、输入关联、几何有效性、所需步骤是否存在、数值是否有限及相应终止/收敛证据。发现错误应非零退出并保留诊断及已有日志；程序退出 0 但科学验证失败，依然不能完成该研究步骤。

跨环境核验使用同方法、同设置的能量与几何差异，容差由各方法 Skill 按单位和收敛参数明确记录；不能要求跨平台逐字节相等，也不能用不同方法的绝对能量高低直接判断优劣。结果缺失时填缺失原因，不编造参考值。

### 3.5 Shell 与输入生成

- 优先直接 argv 调用 Python/runner；使用 Runtime 提供的日志捕获，通常无需 `tee`。
- 必须用 shell 时，执行管道的那一层 Bash 显式启用 `pipefail` 并保留真正返回码。外层设置无法保证独立的内层 `bash -lc` 继承该行为。
- 不以 `grep ... || true` 吞掉必需输出缺失；清理及日志采集不能覆盖主程序返回码。
- 输入通过模板或结构化脚本写出并检查，避免复杂 shell 转义改变 XYZ 换行、路径或参数。对 t006 式输入做结构校验，不仅检查文件存在。
- 路径统一相对有效 Job 工作目录；输入模板、脚本和输出声明使用同一约定。

### 3.6 领域代码恢复清单与拆分原则

为每项原有能力建立“历史路径/提交 → 可复用逻辑 → 目标 Skill → 新入口 → 依赖 → 测试 → 已发布状态”清单。下面是首批候选，不表示历史实现已经通过当前版本验证：

| 优先级 | 历史材料，路径相对旧 chemical/providers | 目标归属 | 迁移重点 |
| --- | --- | --- | --- |
| P0 | `chemical_runtime/pyscf/runner.py`、`backends/pyscf_runner.py`、`backends/pyscf.py` | cf22d 的 scripts 与内部模块 | 保留方法构建/色散检查、优化及 SCF 验证；拆除 Backend 注册、固定旧 Attempt 路径依赖 |
| P0 | `chemical_runtime/backends/xtb.py`、`xyz.py` | xtb 的 scripts/解析模块 | 复用参数生成与终止/收敛解析，补齐明确 opt→SP 编排 |
| P0 | `chemical_runtime/backends/gaussian.py` | gaussian 的 scripts/模板 | 分离 prepare/parse 科学逻辑，适配当前输入及输出合同 |
| P0 | `chemical_readiness.py` 中的有效环境检查、`comparison_plan.py` 中的矩阵逻辑 | 方法 Skill / method-selection | 提取纯配置检查和计划生成，不带回 registry 或 capability ID |
| P0 | `report_lib/`，取自 `8f9ec87` 的父提交 | 报告 Skill 或明确负责汇总的 Skill | 复用报告组织/附件校验，输入改为当前导出的证据快照，去除旧 State 路径耦合 |
| P1 | 仍在当前源码的 `email/providers/notify_lib/` | email/scripts 内部库 | 在删除旧 Provider 前完成迁移，不能再次删掉实现只留下说明 |
| 后续能力盘点 | CREST、ASE NEB、scan、结构分析、热化学、render 等 | 相应领域 Skill | 逐项恢复、适配或明确标记未支持，不由名称存在推断功能可用 |

历史代码按职责分三类处理：

1. **保留并适配领域逻辑**：输入校验、方法构造、程序参数、输出解析、单位转换、收敛判定、模板与科学测试。
2. **移交通用 Runtime**：SSH、qsub、任务轮询、持久超时、取消、进程恢复和工作区暂存。不要复制一套到每个 Skill。
3. **移除旧协议耦合**：Provider descriptor/dispatch、capability registry、旧 JSONL 信封、直接写 canonical State 的代码及专属 Host 工具入口。

历史 runner 可以在 Job 管理的进程内调用 PySCF 或同步启动 xTB/Gaussian 子进程，完整传递退出码并受进程组超时取消管理；不能自行后台化、自行 SSH 提交或绕过 Job Runtime 保存另一套任务状态。

不整体 revert 旧栈，也不把旧 Provider 类改名为 Skill 后原样搬迁。拆分的验收是：领域入口可以直接由配置的解释器执行，不需要 Host 或 Provider runtime 才能 import/工作；通过 job_start 执行时又能正确保留所有输入输出及退出事实。

同步迁回历史测试中的科学断言与日志 fixture；将旧协议测试改写为脚本行为测试。历史测试是待审查的回归基线，不是对旧实现正确性的保证。CF22D 尤其要验证实际 PySCF/LibXC/色散依赖和方法构建路径，不能只恢复 `xc="CF22D"` 字符串。

### 3.7 Skill 资源交付、发现与版本绑定

示意目录如下。文件名按实际迁移可调整，但每个对外宣称可执行的入口都必须存在且经过验证：

```text
cf22d/
  SKILL.md / SKILL.zh-CN.md
  scripts/run.py          # 已支持步骤的 CLI，包含或调用结果验证
  scripts/doctor.py       # 有界环境与方法检查，可与 run 合并为子命令
  scripts/lib/            # 该 Skill 的领域实现
  assets/                # 输入模板/小型示例，按实际需要提供
  references/            # 科学边界、参数及恢复说明
```

Skill 入口须给出准确脚本相对路径、解释器选择、参数例子和输出路径，不能再写“使用 Skill driver”却没有 driver 文件。明确记录当前支持/未支持的任务；脚本缺失或依赖不满足时应产生具体诊断，Agent 不应以临时 RHF/grep 替代一个对外声明已实现的标准方法。

Agent 可以为新任务编写组合脚本或扩展已有实现，但标准流程优先使用经过测试的入口。新生成脚本作为新的、需校验的 Artifact 留存；不得把它当成已验证 runner 的等价替代。这降低重复生成程序细节的概率，同时保留 Skill 与 Agent 的灵活性。

资源发布需要同时保证：

- **可发现**：加载 Skill 时能确定其实际安装根，所有脚本和模板引用都可解析。
- **可安装**：发布包包含入口及其 import/模板依赖；全新安装无源码仓库 PYTHONPATH 时仍可运行。科学软件作为安装级依赖检查，不在任务内临时安装。
- **可远程执行**：使用同一 release 的远程资源，或将该次所需的不可变脚本依赖集按目录结构暂存。不能仅传本地脚本绝对路径或只复制一个缺少内部 import 的 run.py。
- **可追溯**：记录实际执行的脚本、内部模块和模板 digest，以及 Skill/release 版本、程序/库版本；一个运行绑定一种资源版本，排队后升级不改变其脚本。
- **可验证**：发布前检查文档引用存在，再在安装包上运行 doctor、输入生成、fixture 解析及有限真实计算。只验证 SKILL.md 存在不算能力验收。

当前 extension loader 的 Skill sha256 只检查 `SKILL.md`。实施时确认发布包是否已有完整文件 digest，优先复用；为实际脚本/模板补充资源清单及运行 provenance，不能把入口 Markdown 的 hash 当作整个 Skill 实现的版本保证。这是资源完整性记录，不是新的可执行 capability 注册表。

跨 Skill 公共模块仅在确有复用时提取为普通版本化库，并确保随包可用；其内部不得重新加入按方法分发的注册中心。避免用“公共库”名义重建旧科学执行中枢。

## 4. Job Runtime 的通用可靠性修复

### 4.1 统一公开工具与内部合同

当前公开 `job_start` 已支持任意 command，但未暴露内部已有的部分关联与 metadata 字段，outputs 也只有 path/media_type。需要贯通工具 schema、Host 转发、Python 适配层、JobSpec、存储和返回值，不能只改最底层。

拟补齐的通用字段如下，名称在实现时统一并保留明确的兼容规则：

| 字段/行为 | 设计 |
| --- | --- |
| Node / Attempt | 有效研究 Node 的启动自动登记/绑定 Attempt，返回独立 jobId 和 attempt_id；显式绑定已有 Attempt 时验证归属与可启动状态 |
| 输入映射 | 支持 source → destination 的明确映射及 digest；兼容旧字符串输入，不以 basename 偷偷覆盖同名文件 |
| cwd | 以隔离的 Job root 为默认，公开 cwd 表示其中的相对子目录，返回实际路径；废除“接受参数却忽略”的行为，旧用法给出明确迁移诊断 |
| outputs | 增加 required、可选 min_bytes；必要时声明媒体类型。只对指定结果文件要求非空，空 stderr 合法 |
| metadata | 只保存不透明、可审计的普通元数据，如脚本版本/摘要；Runtime 不根据其中方法名路由 |
| resources | 通用 CPU、内存、walltime 请求贯通平台适配；实际值回执可查。不支持的参数明确报错 |
| 启动请求身份 | 持久请求 ID 支持查询和重复请求去重；遇到不确定提交状态先 reconcile，不自动重发 |

内部已有字段不能视为公开能力已经可用。新增字段应覆盖从工具调用到落盘再到重启读取的合同测试。

### 4.2 分开记录执行、收集、验证

建议分别记录：执行状态与真实 exit code；产物收集状态及每项校验；Skill 科学验证结果及来源 Artifact。以下是拟议状态语义，不表示现有 API 已实现这些字段：

- `exit_code != 0`：执行失败，仍允许收集日志和部分结果。
- `exit_code == 0` 且必需文件缺失：进程完成，但产物不完整；保留退出 0 的事实，不能将整个任务宣称可用。
- 文件完整但 Skill 验证失败：科学步骤失败或需解释，不能直接生成成功 Finding。
- SSH 暂时不可达/调度器信息无法解析：状态未知，保留最后确认状态及时间，不伪装为持续运行或已失败。

Runtime 不通过 stderr 中是否出现 `Traceback` 判断科学有效性。Skill 的结构化验证结果由 Agent 读取并登记；通用 Runtime 只保证命令和产物事实。

### 4.3 本地任务持久性

- 用独立于 Host 内存的监督进程或等效持久执行机制写原子 exit receipt；Host 重启后可以恢复日志、退出码和任务身份。
- 超时在无人轮询时也生效，取消作用于正确的进程组。验证 PID 与启动身份，避免 PID 重用后误杀其他程序。
- 父进程退出、子进程仍运行、僵尸进程、Host 崩溃分别处理，不能仅依赖内存中的 Popen。
- 不能恢复真实退出码时标记 unknown 并 reconcile，不从“PID 不存在”推导成功。

当前工作树已有本地进程恢复修改；实施前先审查差异，补缺口，避免覆盖已有工作。

### 4.4 远程调度与收集

- 正确区分 Q/R/H 等调度状态，保留调度器原始状态和更新时间。未知格式/查询失败返回 unknown。
- 优先检查持久终态回执，再结合调度器信息；调度器列表中消失本身不证明成功。
- 提交脚本保证正常失败路径也写退出回执；不能简单加 `set -e` 使回执写入被跳过。强制终止或节点失联等无法写回执的情况由调度器/accounting 与 reconcile 补充。
- timeout 与队列 walltime 语义清楚，等待时间和运行时间分别记录；不把已有 timeout_seconds 当作已经作用于调度器。
- 明确暂存输入集合、目录布局和输出收集清单，避免整体工作区同步夹带无关文件、凭据或产生 basename 冲突。
- 收集可重试，digest 稳定；中断不登记半个 Artifact。失败 Job 的日志仍可收集。
- SSH 断连后的恢复必须查询既有 scheduler ID/提交标识；提交响应丢失时不能直接创建第二个任务。无法证明是否提交成功时保持待核查。

## 5. Research State、证据与 Agent 生命周期

### 5.1 Job 与 Attempt 贯通

采用统一状态事务入口登记 Attempt。推荐顺序：验证 Node/决策 → 写入持久启动 intent 与 Attempt → 执行提交 → 持久回执绑定 Job/scheduler ID → 更新 Attempt。跨进程/远程提交不可能靠单次数据库事务实现原子性，应通过持久 intent、幂等查询和 reconcile 收敛。

启动失败也保留失败 Attempt；改变输入或科学参数重算时建立新 Attempt 并链接前次原因。通用维护 Job 可无研究 Node，但此类 Job 不得冒充研究 Attempt。`jobId` 与 `attempt_id` 始终是不同身份，不再互相充当。

`waiting_external` 使用工具返回的真实 Attempt 引用，并持久保存相关 Job、等待原因和恢复条件；未知提交可指向已创建、处于待核查状态的 Attempt。禁止伪造 Attempt、为绕过校验而省略引用，或把正常等待改写成 blocked。

### 5.2 Artifact 与研究关系

输出收集后登记 Artifact payload、生产 Job 和真实 producer Attempt，保存路径、digest、媒体类型、输入依赖及 parser/脚本版本，再通过 Research State 事务提交 Node/Attempt/Artifact/Finding 关系。

`artifact_register/create` 返回存储回执不应被解释为研究图已关联。`artifact_link` 必须真正持久化到统一状态入口并支持幂等恢复；不能只返回成功形状的对象。`artifact_derive` 如仍只记录派生描述，就应明确语义；实际分析通过 Skill 脚本执行后登记结果，避免虚构派生数据。

先存 payload 后写研究关系时，允许事务失败后存在待关联 payload，并提供恢复路径。关系事务重试不重复生成 Finding；失败尝试和诊断同样保留为证据。

### 5.3 多 Job 交错与门禁

以作用域明确的操作权限替代过粗的单一阶段限制：运行期间允许检查任务、收集结果、登记当前 Attempt 的证据/失败、更新其依赖状态、保存等待点。修改研究目标、扩大范围或新科学决策仍遵守原决策规则。

不全局放开 execute → 任意 advance。为合法的 execute → interpret/checkpoint → execute 路径提供明确转换；生命周期应能承认“一个 Job 完成，另一个仍在运行”。每个分支独立完成或阻塞，失败分支只阻塞其依赖项。

Agent 在工具拒绝后读取结构化恢复建议，修复计划或阶段一次；反复相同错误必须停下并记录问题，不能循环猜测引用。更新现有 lifecycle recovery 测试覆盖 t006 的交错流程。

### 5.4 后台等待与唤醒

先修复/替换当前缺失 monitor.py 的调用链，建立通用 Job 监测与同一研究会话的持久唤醒绑定。Monitor 只产生“Job 状态变化/可收集/异常待核查”事件，Agent 恢复后依据 Skill 解释并继续。

事件去重、重启恢复、确认回执及退避必须持久；状态未变保持安静。完成事件和用户授权的邮件事件分开，Monitor 不直接发送研究邮件。若当前部署没有可运行的后台 worker，应明确提示无法自动续跑，不能把保存 waiting checkpoint 宣称为自动监测已启用。

## 6. 邮件完整迁移为 email Skill

### 6.1 目标流程

`研究结果与报告已登记 → Agent 读取 email Skill → 准备请求及附件清单 → 本地 job_start 运行 Skill 发送脚本 → 收集回执 → 登记通知结果`。

科学完成条件由研究计划和 Skill 决定；邮箱不可用只影响通知，不回滚已完成计算。用户仅要求完成时通知，就不会因一个 Job 结束而发送一封邮件。部分失败报告、进度通知等只有在用户要求的范围内触发。

用户原本明确要求的收件人、内容和发送条件继续有效，不为同一授权重复确认；新增收件人或扩大通知范围时才补充必要信息。本次只是制定方案，没有实际发送邮件的动作。

### 6.2 复用发送实现，移除 Provider 入口

现有 `extensions/email/providers/notify_lib/` 已有 SMTP/ClawEmail、配置读取、锁和回执逻辑，优先迁移复用，不从零重写 SMTP。

拟提供 `extensions/email/scripts/email_cli.py` 及内部库，配套更新 SKILL.md、SKILL.zh-CN.md 和 references。建议命令为：

- `check`：校验安装配置与附件规则，默认不发送、不进行带副作用的试投递。
- `prepare`：形成冻结的邮件请求、内容摘要、附件 digest 和稳定发送身份。
- `send`：读取已准备请求，通过配置的传输发送并写回执。
- `status`：读取本地回执；只有传输确实支持查询时才查询远端，不虚构 SMTP 查询能力。

这些是普通 Skill 脚本子命令，不注册成四个 Host 工具。脚本显式接收工作区根/请求文件；Job cwd 与研究工作区不同，不能靠当前目录猜配置、附件和历史回执位置。

发送通过本地 Job 执行，声明请求、报告等输入和回执输出。SMTP 密钥只从安装级私有配置/env 引用读取，不写入 argv、请求、报告、日志或远程暂存目录。安装配置中的收件人默认沿用，授权与实际收件人绑定并在发送前复核。

### 6.3 去重与不确定投递

去重键基于稳定的通知身份：研究/用户请求身份、事件、收件人及冻结正文/附件版本。不得包含新 Job ID、执行时间或无关 research revision，避免一次恢复变成新邮件。单独记录传输配置版本，轮换密码不意味着再次通知。

发送前持久写 sending，使用跨进程锁；成功保存 sent，重复请求返回已有回执。这里的成功指传输接受，不能声称对方收件箱已送达或已阅读。确定性 Message-ID 便于追踪，不能保证 SMTP exactly-once。

在 SMTP DATA 后断连或发送后落盘前崩溃时，结果可能 unknown。不能自动无限重试或将 unknown 当作 failed；支持供应商查询时核查，否则保留未知状态并说明再次发送可能重复。确定未接受的失败才按有上限的退避重试。

Job Runtime 的重试/恢复不能替 email 脚本决定重新发送。恢复任务先检查稳定回执；取消本地发送进程也不能撤回服务器已接受的邮件。

### 6.4 附件与历史回执迁移

现有发送代码依赖旧 `reports/<package>/`、`ts-report-package/5`。新路径接收当前 Artifact/报告文件及 digest，发送前验证文件内容与已准备请求一致，限制在授权工作区/附件集合内。

保留历史 sent/unknown 回执，提供旧请求身份到新身份的兼容查询或迁移索引，避免升级后重发。无法可靠匹配的旧请求维持待核查，不能当作从未发送。

### 6.5 必须同步移除的调用链

| 位置 | 改造 |
| --- | --- |
| `extensions/email/manifest.json` | 删除 notify_send Provider 注册，保留 Skill 与脚本资源 |
| `apps/app-server/pi-native-notify.mjs` | 移除原生通知工具/Provider 桥接入口，迁移可复用逻辑至 Skill |
| `packages/agent-runtime/host-api/tools.mjs` 及相关别名/元数据 | 移除 notify_send/notify 暴露，更新工具目录和协议检查 |
| `apps/app-server/notification-dispatcher.mjs` | 移除 Host 直接调用邮件 Provider 的路径 |
| `apps/app-server/pi-monitor-worker.mjs` | 保留通用监测和 wake，删除自动发送邮件通道；迁移旧通知绑定 |
| `apps/app-server/server-tools/extensions.json`、原生工具工厂、打包清单 | 同步移除 notify_send，重新生成清单和校验 hash |
| `extensions/email/providers/notify_lib/`、`notify_provider.py`、descriptor | 先迁移发送库及历史兼容，再删除旧入口与协议文件 |

旧 Monitor 通知队列切换前停止旧发送消费，导入回执/待处理身份，再启用 Agent + Skill 路径；避免两条路径同时投递。普通 SMTP/ClawEmail 作为 Skill 内部传输实现可保留，不能再依赖 TSPi Provider dispatch。

## 7. 旧协议、包装与文档清理

### 7.1 化学残留

删除无调用价值的 `createChemicalToolFactories` / `createChemicalTools` 及 `server-tools/chemical-tools.mjs` 包装，去掉总工厂的空扩展。更新 `scripts/package_inventory.py` 中仍打包 chemical-tools 的项目。

这项清理本身不会修复 t006 的科学错误，不能把删除空函数作为主要验收。核心是 Skill 能正确生成并验证实际执行。

### 7.2 Manifest 与 Provider runtime

当前 `tspi-extension/1` schema 和 loader 要求 providers 数组，所以 `providers: []` 目前可作为兼容占位。迁移分两步：先移除实际 Provider 依赖；再调整 manifest 合同为 Skill 资源模型，更新 loader、hash 生成、安装器和合同测试。

若项目需要读取旧安装包，使用明确的版本兼容读路径；旧 providers 字段可以被识别为历史数据，但不自动恢复执行注册。最终新包不再以 Provider 描述科学或邮件能力。

对 `packages/agent-runtime/providers/dispatcher.mjs`、`apps/agent-cli/provider_runner.py`、`packages/tspi-provider-runtime` 及旧 calculation contracts 做完整调用/打包/安装扫描。确认无活跃依赖再移除，历史回执解码可保留为只读兼容。当前已知应用调用主要是两条邮件路径，不等于所有测试与打包引用已经清空。

### 7.3 文档和测试同步

改写 `ARCHITECTURE*.md`、`ARCHITECTURE_BOUNDARIES.md`、`EXTENSIONS*.md`、`COMPUTE_MATRIX_AND_SCRIPT_PLAN.zh-CN.md` 及 Skill reference。废弃文档要明确标记，不让 Agent 同时读到互相冲突的有效架构描述。

修正 `test_extension_contract.py` 中“验证 chemical providers”却断言空集合并继续空循环的测试；扩展现有 `test_skill_execution_contract.py`，不能仅靠搜索是否出现 job_start/registry 字符串证明执行正确。

检查英文/中文内容、Skill hashes、server 工具清单签名/摘要和发布包内容一致，尤其保证 Skill 脚本实际随包安装且相对路径可解析。

## 8. 实施顺序与交付拆分

优先级表示实施依赖与风险，不代表后续项可以不做。科学和邮件都必须完成迁移，才能宣布本方案闭环。

| 阶段 | 交付内容 | 主要代码范围 | 阶段验收 |
| --- | --- | --- | --- |
| S0：基线 | 冻结 t006 证据、梳理 dirty diff、盘点被删除领域实现/测试、建立迁移清单 | 本文、Git 历史、回执、安装清单 | 区分删除协议与丢失能力；每项能力有去向 |
| S1：P0 Skill 可执行资源与科学正确性 | 审查迁回三种方法 runner/解析器/测试及最小报告能力，补齐环境与 opt→SP | `extensions/chemical/skills/`、相关测试与打包 | 安装包有真实脚本入口；不再把 RHF 当 CF22D；失败阻止依赖 SP |
| S2：P0 执行合同 | 输出约束、路径/输入映射、退出码、远程状态与提交恢复 | `host-api/tools.mjs`、`tspi_runtime/execution.py`、`job_runtime/` | 启动、失败、收集事实可信；字段端到端有效 |
| S3：P0 状态闭环 | Attempt、证据持久化、阶段转换、合法等待 | `research-state/`、`tspi_runtime/evidence.py`、`host-api/lifecycle.mjs` | 运行中可记证据；waiting 引用真实 Attempt；重启不丢关联 |
| S4：P1 持续执行 | 本地监督持久性、超时、通用 Monitor wake | `job_runtime/local.py`、`remote.py`、`pi-monitor-worker.mjs` | 无轮询也能超时；重启与唤醒能续跑；无人值守不冒充可用 |
| S5：P1 邮件 Skill | 脚本、回执去重、附件迁移、删除两条 Provider 调用 | `extensions/email/`、通知桥接/dispatcher/工具清单 | 只通过 Skill+Job 发送；mock 重复请求只投递一次；未知结果不盲重试 |
| S6：P1 协议收尾与发布 | 残留清理、文档、hash、安装包、会话版本切换 | manifests、loader、package inventory、docs、contracts | 新安装包能发现并运行所有 Skill，无科学/邮件 Provider 执行依赖 |
| S7：整体验收 | 故障注入、真实本地/远程矩阵、报告和授权通知 | 下节测试与恢复流程 | 每条需求均有证据，可说明未完成项 |

S1/S2 可以按清晰文件边界推进；S3 依赖稳定的 Job 身份合同。email 脚本提取可独立开始，最终发送链切换依赖 S3/S4 的恢复语义。S6 的清理随阶段同步做，不把全部兼容问题留到最后。

发布约束前移到 S1：标准科学入口的脚本/依赖不存在时，不能以“文档已改为通用 job_start”认定迁移完成。后续删除旧模块须先展示能力迁移清单和对应行为验收，防止再次只留下说明文字。

## 9. 验证计划

本次仅新增方案文档，不安装测试环境或启动服务。后续实施测试的安装、Python 环境和隔离测试根统一位于 `/home/iaw/debug/tspi-test-env`，例如其下 `t006-repair/`。软件检查使用 `/home/iaw/soft` 中的现有安装。

测试运行使用独立工作区和凭据替身。所有启动的服务、mock SMTP、worker 和临时任务在 finally/测试结束清理中停止并删除；远程测试 Job 也登记清理结果。不能清理或取消原始 t006 任务作为测试清理的一部分。

### 9.1 必需故障用例

| 用例 | 必须观察到的结果 |
| --- | --- |
| 系统 PATH 缺 xTB，安装配置可用 | Skill 激活并找到配置程序，不报告“未安装” |
| Python import 失败，经 tee 或嵌套 shell | 修复后的 Skill 保留失败码；失败日志可收集 |
| exit 0 但结果文件缺失/为空/路径错误 | 原始 exit 0 保留，产物校验失败，研究步骤未完成 |
| CF22D 请求却产生 RHF 输入/结果 | Skill 方法核验拒绝；用已核验 runner fixture 和真实实现检查支持判断 |
| 优化不收敛但存在能量字符串 | 不能通过；不提交依赖 SP |
| 只有优化结果、错误结构、NaN 或错误单位 | 对应验证失败，有具体诊断 |
| 同名输入、cwd 子目录、远程收集中断 | 文件不覆盖；布局一致；重试不登记损坏产物 |
| Q/R/H、qstat 格式异常、SSH 断连、提交响应丢失 | 状态真实，unknown 可恢复，无无条件重复提交 |
| Host 在提交/退出/收集/状态登记间崩溃 | intent、Job、Attempt 与 Artifact 可 reconcile；不重复提交或重复证据 |
| 没有轮询、PID 重用、僵尸/子进程 | 超时仍生效；取消不误杀；终态不伪造 |
| 一个分支完成、一个失败、其他仍运行 | 可解释和登记结果；独立分支继续；等待引用合法 |
| 发送前崩溃、发送后回执前崩溃、重复唤醒 | sent 复用、unknown 不盲重试；记录真实投递不确定性 |
| SMTP mock 拒绝收件人或部分接受 | 回执区分接受与失败对象，不把部分接受当全部成功 |
| 升级后重试历史已发送请求 | 兼容查询阻止重复投递 |
| Job argv/日志/远程暂存扫描 | 没有邮件密钥或不相关私有配置 |
| 打包后的全新安装 | 能读 Skill、运行脚本、产生真实回执；不需要科学/邮件 Provider |
| Skill 文档引用不存在的脚本，或脚本缺内部 import/模板 | 发布检查失败，指出缺失资源；不能靠开发机源码路径通过 |
| 暂存到远程后的完整 Skill 脚本依赖集 | 在隔离目录可启动并解析 fixture，实际执行脚本 digest 与提交时一致 |
| 只修改脚本/模板而未修改 SKILL.md | 资源版本/provenance 能反映变化，不把旧入口 hash 当作实现未变 |

科学结果验证应使用能区分成功/失败的真实日志 fixture，配合有限的真实水分子计算；文本快照断言不足以验证方法与科学正确性。邮件自动测试使用注入的 mock SMTP/传输，不向真实收件人发测试邮件。

### 9.2 t006 端到端验收

1. 在新隔离工作区恢复任务矩阵并冻结输入与配置摘要。
2. 跑平台与方法探测，确认本地/远程配置分别有效。
3. 完成六条 opt→SP 链，每步有日志、验证结果、Attempt 和 Artifact；失败分支留下完整原因。
4. 核验同方法本地/远程结果，生成包含版本、设置、能量/结构、差异及异常的报告。
5. 重启一次 Host/worker 验证等待、收集、证据及报告不会丢失或重复。
6. 先用 mock 验证 email Skill 全链路。真正发送最终报告前确认原有用户授权适用于本次恢复报告，且没有同一通知的 sent/unknown 待核查回执；不因本文本身发送。

远程不可访问时，可以完成本地和远程模拟测试，但必须将“真实远程验收未通过”保留为未完成项，不能宣称 t006 整体修复验收完成。

## 10. 发布、历史迁移与 t006 恢复

- 发布前记录当前未提交改动及归属，在其基础上审查整合；不以重置工作树开始实施。
- 生成新 release，更新 Skill、manifest、server inventory 摘要，安装后核对实际路径和内容。源码修改不会自动改变已运行会话使用的 release。
- 明确会话切换边界：保存 checkpoint 和 Job 绑定后，再通过受支持的重启/恢复流程加载新 release；不在运行中混用旧工具 schema 和新实现。
- 保留原始 t006 的回执、日志及状态快照。历史错误结论用补充审计记录纠正，不覆盖原退出码或伪造过去不存在的科学结果。
- 可为历史 Job 补登记带“历史导入”标识的 Attempt 和映射，但保留旧 receipt 为原始证据；只根据已知事实迁移，不补造提交或终止事件。
- 恢复前先查询三个历史 scheduler ID 和相应运行目录；优先收集已有结果。无法确认是否仍运行时，不自动重提同一任务；确需新尝试时记录重算原因及与旧任务的关系。
- 对已确认不合格的 CF22D/RHF 等脚本新建修正后的 Attempt，原始证据继续可查。不会仅换解释器后复用错误科学输入。
- 邮件切换保留历史回执和待处理请求，旧发送 worker 与新路径互斥。回滚部署也不能清除 sent/unknown 或自动重放旧通知队列。

## 11. 最终完成判据

只有以下条件全部有证据，才算修复闭环：

1. 科学方法、流程与邮件发送均由 Skill 指导及脚本实现，通用工具负责执行；没有恢复化学 Capability/Provider 注册表或原生 notify_send 路径。
2. 所有请求的方法与步骤准确执行，环境和输入可追溯；任何阶段失败都不会被 tee、grep 或“文件存在”掩盖成科学成功。
3. 每个研究计算 Job 有真实 Attempt，结果和失败证据落入 Research State；等待、交错执行、重启、远程不确定状态均可恢复。
4. Runtime 提供真实退出码、明确的产物状态、持久日志、有效超时及安全取消；不擅自作科学判断。
5. 完整报告引用实际结果，缺失和不确定项明确；邮件通过 email Skill 按授权触发，回执可靠，重复唤醒不导致重复发送。
6. 真实安装包、双语 Skill 文档、工具合同与当前实现一致，相关测试和本地/远程验收完成，测试服务已清理。

整体修复的中心是：**先保住并迁回 Skill 所需的领域实现，再让科学设计可靠地变成可执行、可验证、可恢复的任务，并让状态和证据跟得上执行。**
