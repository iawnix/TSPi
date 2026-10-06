# TSPi 重构方案：从 Capability-Driven Compute 到 Skill-Driven Research Agent

## 1. 结论和目标

当前 TSPi 已经具备不少可靠的基础设施：单一 Root Agent loop、workspace 绑定、Research State 事务、Artifact digest、bounded context、Monitor 唤醒和 Agent Server session 恢复。这些部分应保留。

主要问题出在计算路径的抽象层次。当前 `compute_run` 把以下职责放在一个调用链中：

```text
选择已注册 capability
→ 生成 calculation intent
→ provider 准备输入和命令
→ 执行本地或远程作业
→ 收集输出
→ 调用领域 parser
→ 调用领域 validator
→ 写 calculation_result
→ 注册 canonical Artifact
→ 为后续 Finding 提供来源
```

这使 Root Agent 只能组合内核已经知道的程序和 provider。Skill 没有真正承担“如何使用一个程序”的职责；它只是 capability 选择流程的说明。

重构目标是把系统恢复成 coding agent 的结构：

```text
Skill / 文档 / 辅助脚本
        ↓
Root Agent 组合 read、write、bash 和长任务工具
        ↓
Job Runtime 负责进程、远端作业、生命周期和 provenance
        ↓
Research State 记录 Artifact、Evidence、Finding 和研究状态
        ↓
Monitor 负责等待、轮询和唤醒
```

内核不再要求 Gaussian、xTB、PySCF 或任意其他程序先注册完整 provider 才能执行。程序的输入格式、命令写法、输出检查和科学解释由 Skill 以及 Skill 携带的脚本提供。

重构后的核心原则：

1. Root Agent 是唯一的科学决策者，也是普通命令组合者。
2. `bash`、`write`、`read` 等通用原语保持通用语义。
3. 长时间计算只是带有 durable handle 的 Job，不是特殊的科学子 Agent。
4. Job 成功、输出收集成功、输出解析成功、科学验证成功是四个独立事实。
5. 原始输出可以直接成为 Research State 的 Artifact，不需要 parser 先验批准。
6. Finding 需要来源 Artifact，但不要求来源 Artifact 经过某个领域 parser。
7. Monitor 只负责外部事件和唤醒，不选择方法、不解释结果、不修改 Finding。
8. Extension 默认提供 Skill、参考资料和可选脚本；provider 只是兼容层或便利适配器。

### 名称约定

本方案将顶层服务正式命名为 **TSPi Agent Server**。它负责托管 Agent session、Research Harness、工具调用、Job Runtime 和 Monitor 的组合。现有代码中的 `Host`、`tspi-host/1`、`host-api` 和 `.pi/app-server-host/` 在迁移期间保留为协议或路径兼容名称，文档和新模块不再把它们当作产品级架构名称。

`Execution Platform` 专指本地机器、SSH 主机、Slurm/PBS/Torque 集群或容器运行时；它不再称为 Compute Host。`Job Runtime` 负责调用这些平台，`Research State Runtime` 负责研究状态，`Research Harness` 负责 turn 和恢复。

### `extensions/` 的保留方式

重构后仍然保留项目根目录的 `extensions/`。它是可安装领域知识包和工作流资源的目录，不再是内核执行器的注册表。没有某个 Extension 时，Root Agent 仍可使用通用 `read`、`write`、`bash` 和 `job_*` 运行程序；安装 Extension 只是让 Agent 获得更完整的 Skill、模板、参考资料和可选 helper。

目标布局示例：

```text
extensions/
  core/                  # 随 Agent Server 发布的 built-in bundle
    manifest.json
    skills/
      orchestration/
      research-state/
  chemical/
    manifest.json
    skills/
      gaussian/
        SKILL.md
        references/
        scripts/
        templates/
        analyzers/
      xtb/
        SKILL.md
        references/
        scripts/
        templates/
        analyzers/
      crest/
        SKILL.md
        references/
        scripts/
        templates/
      validation/
        SKILL.md
        references/
  scripting/             # 可选脚本工作流 bundle；不是执行能力 provider
    manifest.json
    skills/
      scripting/
        SKILL.md
        references/
        scripts/
  email/
    manifest.json
    skills/
      email/
        SKILL.md
        references/
    providers/                 # 仅保留外部通知适配器
```

现有 `extensions/chemical/providers/*_compute_provider.py` 中的输入构造、输出解析和验证逻辑可以迁移到具体 Skill 目录下的 `scripts/`、`analyzers/` 或普通 Python library。它们由该 Skill 明确调用，或者由 Agent 通过 `bash`/`job_start` 执行；它们不能成为 Job 启动和原始 Artifact 收集的前置条件。

### Skill 资源必须以 Skill 为边界

按照 OpenAI Skill 的自包含组织方式，`SKILL.md`、references、scripts、templates 和可选 analyzers 默认都应该放在同一个 Skill 根目录下：

```text
extensions/chemical/skills/gaussian/
  SKILL.md
  references/gaussian_validation.md
  scripts/gaussian_summary.py
  templates/optimization.gjf
  analyzers/gaussian_output.py
```

Skill 正文使用相对路径引用这些资源。Agent 只有在加载 Gaussian Skill 时才需要看到这些资源的名称和内容；它们不应作为 Extension 全局资源自动注入上下文。

只有确实被多个 Skill 共享的代码才放在 Extension 的 `lib/` 或 Python package 中。共享知识优先拆成单独的 Skill，避免在多个 Skill 之间使用隐式相对路径或复制文件。

脚本执行本身不需要单独的 Extension。`bash` 负责短命令，`write` 负责生成脚本，`job_start` 负责跨 turn 的长任务。只有在需要脚本可复现、输出声明、批处理或示例流程时，才提供一个可选的 `scripting` Skill。

`extensions/script/providers/script_compute_provider.py` 会被删除。需要脚本可复现、输出声明、批处理或示例流程时，可以提供可选的 `extensions/scripting` bundle；它只包含 Skill 和示例。`extensions/email` 可以继续保留 provider，因为发送邮件本身是一个外部副作用适配器，不是科学计算执行器。包内的 `apps/app-server/server-tools/` 继续承载 TSPi Agent Server 的核心工具，不属于 Extension 的领域 provider。

### `apps/`、`packages/`、`extensions/` 的目录命名

这三个目录可以保留，但必须分别表达不同边界：

| 目录 | 语义 | 判断标准 |
| --- | --- | --- |
| `apps/` | 可执行的组合根和客户端入口 | 是否启动一个 Agent、CLI 或本地应用进程 |
| `services/` | 独立部署的长期服务 | 是否拥有独立 daemon、socket、HTTP/WSS 或 scheduler 生命周期 |
| `packages/` | TSPi 内部可复用运行库和协议 | 是否被多个 app/service 依赖，且不应直接作为领域安装包交付 |
| `extensions/` | 可安装资源 bundle 的统一命名空间 | 是否通过 manifest 向 Agent 增加 Skill、参考资料、模板、helper 或 analyzer |
| `extensions/core/skills/` | TSPi 内置核心 Skill | 是否属于所有 Research Agent 都需要的基础研究流程 |
| `components/` | 可选 UI 或客户端组件 | 是否主要提供展示、Web provider 或前端集成 |

因此，目标布局建议为：

```text
apps/
  agent-server/       # TSPi Agent Server 的组合根
  agent-cli/           # ResearchAgent CLI 和客户端入口

services/
  tspi-link-relay/     # 独立 Link Relay daemon

packages/
  agent-core/
  agent-runtime/
  research-state/
  research-memory/
  job-runtime/         # 由 research-compute 重命名
  research-state-bridge/
  tspi-foundation/
  tspi-link/

extensions/
  core/                  # 始终启用的内置 Extension bundle
    manifest.json
    skills/
      orchestration/
      research-state/
  chemical/              # 可选领域 Extension bundle
  scripting/             # 可选脚本工作流 bundle
  email/                 # 可选外部通知 Extension bundle

components/
  ts-web/
```

`apps/app-server` 应在彻底重构中改名为 `apps/agent-server`。现有 `apps/app-server/*.mjs` 可以分批迁移，旧 import path 只在兼容阶段保留。`packages/research-compute` 应改名为 `packages/job-runtime`，因为它的新职责是通用 Job 执行、收集和 reconcile，而不是科学计算能力。

`extensions` 可以称为 Extension package，但它和 `packages` 的含义不同：前者是面向 Agent 的可安装资源 bundle，后者是 TSPi 实现依赖的代码库。文档中统一使用“Extension bundle”避免把两者混成同一种 package。

### Skill 与 Extension 的统一命名空间

建议不要长期同时保留顶层 `skills/` 和 `extensions/*/skills/` 两套 Skill 根目录。统一方案是：

```text
extensions/core/skills/orchestration/
extensions/core/skills/research-state/
extensions/chemical/skills/gaussian/
extensions/scripting/skills/scripting/
extensions/email/skills/email/
```

其中 `extensions/core` 是随 Agent Server 一起发布、始终启用、不可卸载的 built-in bundle；`chemical`、`scripting` 和 `email` 是可选 bundle。`core` 不是需要 provider 注册的能力，而是 Skill loader 的第一个固定输入。

建议 core manifest 使用明确的分发标记：

```json
{
  "schema_version": "tspi-extension/2",
  "name": "tspi-core",
  "version": "2.0.0",
  "distribution": "built_in",
  "installable": false,
  "skills": [
    {"name": "orchestration", "path": "extensions/core/skills/orchestration"},
    {"name": "research-state", "path": "extensions/core/skills/research-state"}
  ]
}
```

这样所有 Skill 都经过同一个 manifest、digest、lazy body loading 和 provenance 流程；Core Skill 与可选领域 Skill 的差异只体现在 `distribution` 和启用策略。迁移期间可以保留顶层 `skills/` 的兼容路径，但新代码、文档和 `package.json` 的 Skill 清单统一指向 `extensions/core/skills/`。

不建议把所有 Extension 内容直接塞进 `skills/`，因为 Extension 还包含脚本、模板、参考资料、analyzer 和外部副作用适配器；`skills/` 只能表示其中的 Agent 指令部分。

## 2. 当前框架审计

### 2.1 当前模块结构

当前主要边界如下：

| 模块 | 当前职责 | 审计结论 |
| --- | --- | --- |
| `packages/agent-core` | session、workspace、turn routing、memory port | 基础边界合理，应保留 |
| `packages/agent-runtime` | Tool contract、Harness lifecycle、Compute/Review 子 Agent、journal | 生命周期和 envelope 有价值；Compute 子 Agent 语义过重 |
| `apps/app-server` | TSPi Agent Server、Pi worker、工具装配、Native bridge、Monitor worker | 作为 control plane 合理，但把 compute provider 绑定得太深 |
| `packages/research-state` | ResearchMap、ChangeSet、Finding、Gate、Attempt、Artifact、liveness | 应继续作为唯一科学状态权威；需要放宽原始 Artifact admission |
| `packages/research-memory` | 从 Research State 构造 projection 和 bounded context | 设计合理，应保留 |
| `packages/research-compute` | intent、capability registry、provider protocol、prepare、submit、collect、parse、readiness | 当前混合了 Job Runtime 与领域科学语义，应拆分 |
| `extensions/chemical` | Gaussian、xTB、CREST、PySCF 的 provider、parser、analysis 和 Skill | Skill 内容有价值；provider 不应是执行前置条件 |
| `extensions/scripting` | 可选脚本工作流说明和示例；执行由核心 Job 原语提供 | 不安装也能运行脚本，Skill 只补充组织和复现建议 |
| `packages/tspi-provider-runtime` | provider JSONL 协议 | 可保留给可选 deterministic helper，不再作为核心执行边界 |
| `apps/agent-cli/monitor.py`、`pi-monitor-worker.mjs` | durable monitor、事件、delivery、wake | 机制有价值，应从 Compute Monitor 改成通用 Job Monitor |
| `components/ts-web`、Link、Phone | 只读展示和远程客户端 | 与本次核心重构低耦合，保持协议兼容 |

### 2.2 主要问题

#### P0：`compute_run` 的完成条件错误

`apps/app-server/pi-native-compute.mjs` 先执行 `collect`，随后固定执行 `parse`。`packages/research-compute/research_compute/control.py` 的 `parse_calculation()` 又要求 provider 提供 parser、parser name、parse artifacts、parsed task validation 和 program outcome。

结果是：

```text
程序成功运行
→ 输出成功收集
→ parser 缺失或 validator 缺失
→ finalize 失败
→ Attempt 可能保持 running
→ calculation_result 不进入 parsed
→ canonical Artifact admission 不发生
→ Root 不能自然创建 Finding
```

执行事实被科学解释失败覆盖，这是最严重的架构错误。

#### P0：Capability Registry 成为 Root Agent 的能力边界

`packages/research-compute/research_compute/provider.py` 的 `ComputeProvider` 同时要求准备、命令构造、输出声明、解析、验证和 Artifact 辅助接口。`capabilities.py`、`readiness.py` 和 intent materialization 又把这些接口放在执行前检查。

这不是普通 coding agent 的 Skill 模型，而是“内核支持哪些程序，Agent 才能做什么”的模型。Root Agent 无法仅通过 `write` 生成 input、通过 `bash` 调用一个新程序、再通过 `read` 分析其输出。

#### P1：Artifact admission 与 parser admission 耦合

当前 `_register_parsed_evidence` 是 canonical Research State Artifact 进入计算证据链的主要路径。collect-only 的原始输出可能只存在于运行目录或 operational result 中，不能自然成为 `create_finding.source_refs`。

正确语义应当是：

```text
文件存在并有 provenance → 可以登记 Raw Artifact
有 parser → 可以生成 Derived/Parsed Artifact
有 validator → 可以生成 validation record
Root 解释后 → 可以创建 Finding
```

#### P1：`compute_readiness` 的语义过宽

当前 readiness 检查 capability、environment、executable、activation、SSH、scheduler、queue 和 scratch。它没有检查科学字段，也不应该检查科学字段，但对外输出容易被理解成“整个计算能力 ready”。

缺少 parser 时仍可能返回 ready；真正失败要到 finalize 才暴露。readiness 应降级为通用 Job probe，或者保留为 Skill 的便利诊断，而不能作为科学能力总门禁。

#### P1：Compute 子 Agent 是固定 action executor，不是有价值的 Agent

`packages/agent-runtime/agents/compute` 创建 task packet、action plan 和 output schema，但不做方法选择、文件读取、命令生成或科学推理。`pi-native-compute.mjs` 负责实际 `prepare → submit`、`status`、`collect → parse`。

这层增加了 journal 和约束，却没有增加 Agent 决策能力。它应改名为 `JobExecutionTask`，或者直接并入 Job Runtime。

#### P2：Review 子 Agent 的作用应明确为可选 advisory

Review 子 Agent 有真正的模型调用，但只读 Artifact，输出反方意见、缺失证据、冲突和建议。它不应成为研究状态推进的必要环节，也不应自动写 Finding。当前边界基本正确，只需要从“核心工作流组件”降级为可选工具。

#### P2：Extension manifest 仍以 provider 为中心

当前 `extensions/*/manifest.json`、descriptor 和 provider entry 把运行能力描述成可注册对象。对于 Skill-driven 模型，manifest 的核心应该是 Skill、参考资料、可执行 helper 和可选 analyzer；provider 只作为兼容或优化路径。

### 2.3 应保留的基础设施

- Research State 的单一权威和 ChangeSet 事务。
- workspace root/session 绑定。
- Artifact digest、来源、lineage 和引用完整性。
- Agent Context 的 bounded projection。
- Monitor 的 durable registration、event、delivery、claim 和 wake。
- Agent Server 的 tool envelope、幂等、恢复和 session lane。
- 本地/远端 transport adapter 的可替换性。
- Link、Phone、TS Web 的只读和传输协议。

## 3. 目标总体架构

```text
┌──────────────────────────────────────────────────────────────────┐
│ Root Agent / Pi Agent Loop                                       │
│                                                                  │
│  Skill metadata/body  +  research context  +  normal conversation│
│  read / write / edit / bash / job_* / artifact_* / research_*    │
└───────────────┬──────────────────────────────────────────────────┘
                │ function calling
┌───────────────▼──────────────────────────────────────────────────┐
│ TSPi Agent Server / Research Harness                            │
│                                                                  │
│ workspace/session binding · tool envelope · timeout · recovery   │
│ turn admission · monitor wake · operation receipt                │
└───────┬──────────────────────┬───────────────────┬───────────────┘
        │                      │                   │
┌───────▼────────┐   ┌─────────▼────────┐  ┌───────▼─────────────┐
│ Job Runtime     │   │ Research State   │  │ Monitor              │
│                 │   │                  │  │                      │
│ argv/shell      │   │ ResearchMap      │  │ poll/status          │
│ local process   │   │ Attempt          │  │ durable event         │
│ remote submit   │   │ Artifact         │  │ wake same session     │
│ collect/cancel  │   │ Evidence/Finding│  │ no scientific logic   │
└───────┬─────────┘   └─────────┬────────┘  └─────────┬────────────┘
        │                       │                     │
┌───────▼────────┐   ┌──────────▼────────┐  ┌─────────▼────────────┐
│ local/remote   │   │ workspace files   │  │ Agent Server lane     │
│ adapters       │   │ context/revision  │  │ next_run delivery    │
└────────────────┘   └───────────────────┘  └──────────────────────┘

Extensions:
  Skill text + references + command/helper scripts + optional analyzers
  No provider registration is required for basic execution.
```

### 3.1 核心分层

#### Layer A：Agent primitives

由 Pi 原生工具提供：

- `read`：读取工作区文件或 Artifact excerpt；
- `write`/`edit`：生成 input、脚本、配置和解释结果；
- `bash`：执行短命令、解析命令、生成辅助代码；
- `job_start`：启动可能跨 turn 的命令；
- `job_status`：查询 Job；
- `job_collect`：收集输出；
- `job_cancel`：取消 Job；
- `artifact_register`：登记原始或派生文件；
- `artifact_read`：读取有界内容或 manifest；
- `research_read`、`research_change`、`research_checkpoint`：研究状态读写。

`bash` 与 `job_start` 使用同一个 command model。区别只在于是否需要 durable lifecycle，不在于是否属于某个科学 capability。

#### Layer B：Skill

Skill 是 Agent 的工作说明，不是内核 executable contract。它可以包含：

```text
SKILL.md
references/
scripts/
templates/
examples/
```

Skill 可以说明：

- 如何构造输入；
- 如何选择命令行参数；
- 如何使用环境变量；
- 如何把长任务交给 `job_start`；
- 哪些输出文件值得登记；
- 如何使用 `grep`、Python 或 helper parser 检查输出；
- 哪些字段只能称为 operational observation；
- 哪些证据足以支持某个 Finding；
- 哪些异常需要记录为 IssueFinding。

Skill 不要求内核为每个方法创建 capability id，也不要求 parser 先注册。

#### Layer C：Job Runtime

Job Runtime 是领域无关的 durable process service。它只理解：

- command/argv 或 shell script；
- workspace cwd；
- stdin/input files；
- environment；
- local process 或 remote scheduler；
- timeout、cancel、retry/reconcile；
- stdout、stderr、exit status、scheduler id；
- 输出文件和 digest；
- Attempt provenance。

它不理解 Gaussian route section、频率、SCF、优化收敛或任何科学字段。

#### Layer D：Research State Runtime

Research State 负责规范对象和引用关系：

- Claim、Node、Finding、Gate、Phase；
- Attempt manifest；
- Artifact manifest；
- Evidence Link；
- revision、ChangeSet、冲突和状态转换；
- lifecycle disposition。

它校验对象结构和引用完整性，不校验任意 Artifact 是否具有某个领域 parser。

#### Layer E：Monitor

Monitor 只负责：

- 记录 Job/Attempt 的外部观察；
- 轮询 local/remote adapter；
- 记录有意义的 event；
- 生成 next_run；
- 唤醒拥有该 workspace/session 的 Root Agent；
- 防止重复投递。

Monitor 不调用 parser，不创建 Finding，不推进 Claim/Node 状态。

### 3.2 Pi Agent 工具层与 TSPi 工具层

Pi Agent 本身提供 coding agent 原语。当前依赖版本的默认启用集合是：

```text
read
bash
edit
write
```

Pi 还提供可选的内置工具：

```text
powershell
grep
find
ls
```

`codemode` 和 `tool_search` 是可选的内置扩展；MCP Server 和 Extension 也可以注册自定义工具。`grep`、`find`、`ls` 可以用 `bash` 替代，但独立工具能提供更稳定的参数和结果边界。

TSPi 只增加研究运行时所需的通用工具，不为 Gaussian、xTB 或其他软件各增加一个工具。目标工具集合按职责分组：

```text
Pi built-ins:
  read / write / edit / bash / grep / find / ls

Durable Job:
  job_start / job_status / job_collect / job_cancel / job_probe

Artifact:
  artifact_register / artifact_read

Research State:
  research_read / research_change / research_strategy
  research_interpretation / research_checkpoint

  research_change operations:
    create_claim / assess_claim / revise_claim
    create_finding / link_evidence / evaluate_gate

Optional advisory/integration:
  review_run / review_respond / notify_send
```

当前的 `compute_environment`、`compute_catalog`、`compute_readiness`、`compute_run`、`artifact_import`、`analysis_run`、`artifact_render` 和 `report_build` 是旧架构工具。迁移期间保留兼容别名，目标映射如下：

| 当前工具 | 目标工具或处理方式 |
| --- | --- |
| `compute_run` | `job_start/status/collect/cancel` 的兼容 facade |
| `compute_readiness` | 可选 `job_probe`，只探测执行环境 |
| `compute_environment` | `execution_environment`，返回 Platform/Environment 信息 |
| `compute_catalog` | Skill/software inventory 查询，不作为执行门禁 |
| `artifact_import` | `artifact_register` |
| `analysis_run` | Skill 下的 `scripts/`、`analyzers/` 或普通 `bash/job` |
| `artifact_render` | 可选 Artifact Skill/helper |
| `report_build` | 可选 report Skill/helper |

Pi 的原生工具不会知道 ResearchMap；TSPi 的 Research 工具不会改变 `read`、`write`、`edit` 和 `bash` 的普通语义。`assess_claim` 和 `revise_claim` 仍然通过 `research_change` 的事务 envelope 提交，不增加一个绕过 Research State revision 的快捷写接口。

### 3.3 TSPi Agent Server、Job Runtime 与 Execution Platform

**TSPi Agent Server** 是应用级 control plane，负责：

- 创建、恢复和关闭唯一 Root Agent session；
- 将 TUI、Phone、Web 和 Monitor 连接到同一个 Agent lane；
- 装载 Core/Extension Skill 和 TSPi 工具；
- 绑定 workspace/session，处理工具 schema、超时、取消、幂等和恢复；
- 调用 Research State Runtime 和 Research Memory；
- 调用 Job Runtime 并安排 Monitor wake。

Agent Server 不负责 Gaussian 解析、科学验证或 Finding 决策。旧代码中的 `Host`、`tspi-host/1`、`host-api` 和 `.pi/app-server-host/` 在迁移期保留为协议/路径兼容名；新架构统一使用 `TSPi Agent Server`。

**Job Runtime** 负责通用 Job 的 prepare、submit、status、collect、cancel 和 reconcile。它可以选择不同的 Execution Platform：

```text
LocalProcessAdapter
SSHAdapter
SlurmAdapter
PBSTorqueAdapter
ContainerAdapter
```

**Execution Platform** 描述程序在哪里运行；**Execution Environment** 描述如何激活和配置该平台上的环境：

```text
Platform: local / ssh / slurm / pbs / container
Environment: cwd / activation / env vars / scratch / resource defaults
Software observation: command / resolved path / version / observed time
```

Software inventory 和 `job_probe` 只提供观察结果。Agent 可以直接提交未知命令；命令不存在时 Job 返回 `executable_not_found`，不会因为没有 capability descriptor 而提前拒绝。

**Research Harness** 负责 turn、工具生命周期、checkpoint、Monitor wake 和恢复；**Research State Runtime** 负责 ResearchMap、Artifact、Evidence、Finding、revision 和 ChangeSet。四者都不承担领域 parser。

### 3.4 Agent Loop、上下文和 Subagent

普通研究流程只有一个 Root Agent loop。Skill、Research Context、Job 状态和 Monitor wake 都重新进入这个 loop；Monitor 不创建第二个科学决策者。

Compute 子 Agent 在目标架构中删除。它当前的 task packet、固定 action plan、`compute_result` 和模型 Harness 只是在包装确定性的 Job 操作，迁移后改为 Job action receipt：

```text
Root Agent → job_start → Job Runtime
Root Agent ← job_id / attempt_id / monitor_id
Monitor → 同一 session 的 wake
Root Agent → job_status / job_collect
```

Review 子 Agent 可以保留，但只作为 bounded advisory second opinion。它可以读取有界 Artifact excerpt，返回事实、缺失证据、冲突和建议；它不能直接写 ResearchMap、选择方法、启动 Job 或改变 Claim/Node 状态。Root Agent 负责决定是否通过 `research_change` 采纳意见。

每个 turn 的上下文由 Research Memory 从 Research State revision 重新构造，包含当前 focus、Node/Claim、Attempt/Job 摘要、Artifact manifest、liveness 和 Skill metadata。完整 Skill 正文、references、大文件和历史记录按需读取，不复制成第二份科学状态。

### 3.5 Pi Agent 与 TSPi Research Agent 的边界

TSPi 不需要复制一套新的模型 Agent loop，也不应把 Research Map 的状态机塞进 Pi 的基础工具语义。Pi Agent 仍然负责通用的 coding agent 循环：接收上下文、请求模型生成、执行 tool call、把 tool result 放回上下文、继续当前 turn，直到模型结束、用户中断或 Harness 暂停。

Pi Agent 保持不变的部分包括：

- 模型 turn、流式输出和上下文历史；
- tool call 的 dispatch、结果返回和错误传播；
- `read`、`write`、`edit`、`bash` 等 coding tools 的普通语义；
- 用户中断、超时和模型响应结束；
- Skill 正文作为上下文指令加载的基本机制。

TSPi 在 Pi 之上增加的是 Research Agent 的运行时边界：

| 扩展层 | TSPi 增加的内容 | 是否修改 Pi 基础 loop |
| --- | --- | --- |
| Agent Server / Research Harness | workspace/session 绑定、turn lane、checkpoint、恢复、Monitor wake、幂等 receipt | 否，包在 loop 外部 |
| Research Memory | 从 Research State revision 生成 bounded context 和 `research_obligations` | 否，作为 turn 输入 |
| Job Runtime | `job_start/status/collect/cancel/probe`、长任务生命周期、local/remote reconcile | 否，作为工具调用 |
| Research State Runtime | Claim、Node、Finding、Artifact、EvidenceLink、Gate、assessment、revision 和 ChangeSet | 否，作为事务工具调用 |
| Core Skills | 假设提出、证据解释、Node/Attempt 选择和研究推进规则 | 否，作为 Agent 指令 |
| Domain Skills | Gaussian、xTB、PySCF 等程序的输入、观察和解释方法 | 否，作为可选领域知识 |
| Monitor | 外部 Job 轮询、事件记录和同一 session 唤醒 | 否，不创建第二个研究 Agent |

因此，Pi Agent 是通用的“会使用工具的 Agent loop”，TSPi Research Agent 是“带 Research State 上下文、证据工具、长任务恢复和研究 Skill 的 Pi Agent”。两者的差异来自状态、工具、上下文和 Skill，而不是另一个模型、另一个 Compute 子 Agent 或另一套隐藏推理循环。

## 4. 目标数据模型

### 4.1 Job

```json
{
  "schema_version": "research-job/1",
  "job_id": "job_123",
  "node_id": "node_1",
  "command": {
    "mode": "argv",
    "argv": ["g16", "input.gjf"],
    "cwd": "nodes/node_1/jobs/job_123"
  },
  "inputs": ["art_input"],
  "environment": "local",
  "status": "running",
  "backend": {"kind": "local_process"},
  "started_at": "...",
  "scheduler": null,
  "provenance": {
    "skill": "chemical/gaussian",
    "skill_digest": "sha256:...",
    "command_digest": "sha256:..."
  }
}
```

`command` 可以来自 Skill，也可以来自 Root Agent 刚刚写入的脚本。Job Runtime 只记录它，不判断它是不是 Gaussian。

### 4.1.1 Platform、Environment 和 Software Observation

这些对象描述运行条件，不描述科学 capability：

```json
{
  "platform": {
    "id": "cluster_a",
    "kind": "ssh_scheduler",
    "scheduler": "slurm",
    "host": "cluster.example.org"
  },
  "environment": {
    "id": "gaussian_cluster",
    "platform_id": "cluster_a",
    "activation": ["source /opt/gaussian/g16/bsd/g16.profile"],
    "scratch": "/scratch/$JOB_ID",
    "resources": {"cpus": 16, "memory": "32G", "walltime": "24:00:00"}
  },
  "software_observation": {
    "command": "g16",
    "resolved_path": "/opt/gaussian/g16/g16",
    "version": "G16.C.02",
    "observed_at": "..."
  }
}
```

`software_observation` 可以来自 `job_probe`，也可以来自 Job 启动时的实际解析。它写入 provenance，供复现和诊断使用；缺少 observation 不阻止 Agent 直接执行命令。

### 4.2 Attempt

Attempt 是 Research State 中的运行记录，推荐状态：

```text
created → prepared → submitted → queued → running
       → collected → succeeded
       → failed / timed_out / cancelled / unknown
```

`collected` 是合法的终态候选，表示原始输出已经成功收集。它不要求 `parsed`。

如果需要保留解析阶段，可以把解析作为独立 Artifact derivation：

```text
Raw Artifact → Derived Artifact(kind=parsed) → Validation Record
```

不再把 `parsed` 作为 Attempt 成功的唯一条件。

### 4.3 Artifact

Artifact manifest 至少包含：

```json
{
  "artifact_id": "art_...",
  "node_id": "node_1",
  "kind": "raw_output",
  "path": "nodes/node_1/jobs/job_123/gaussian.out",
  "media_type": "text/plain",
  "size_bytes": 12345,
  "sha256": "sha256:...",
  "source": {
    "job_id": "job_123",
    "attempt_id": "attempt_1",
    "role": "stdout"
  },
  "annotations": {
    "program": "gaussian",
    "format": "gaussian-output"
  }
}
```

`program`、`format`、`parser` 都是 annotation，不是 Artifact admission 的必填能力。未知格式也可以登记为 `application/octet-stream` 或 `text/plain`。

### 4.4 Finding

`create_finding.source_refs` 只要求引用已登记 Artifact。Finding 的 provenance 应明确区分：

```json
{
  "provenance": {
    "basis_artifacts": ["art_raw_output"],
    "interpretation_mode": "root_agent_reading",
    "parser": null,
    "validation": "unavailable"
  }
}
```

没有 parser 时，可以创建“从原始输出读取出的观察”或 IssueFinding；不能把它标成经过领域验证的结论。这个限制属于 Finding 的 provenance 和表达，而不是阻止 Artifact 入库。

### 4.5 Artifact 是重构后的核心连接层

Artifact 不会被 Job Runtime 取代，也不会因为移除 capability/provider 而变成普通文件。它仍然是 Job、workspace、Research State、Skill helper 和 Finding 之间的统一证据对象：

```text
物理文件 / stdout / remote output
        ↓ register
Artifact Manifest
        ↓ source_ref / evidence link
Finding / Claim / Gate
```

必须保持一个 canonical Artifact Registry。Job Runtime 可以先写 operation receipt 或 provisional output，但 collect 完成后必须把输出登记为 Research State 可引用的 Artifact；不能同时维护一套 operational ArtifactStore 和一套 canonical ArtifactStore。

Artifact admission 只做通用不变量检查：

- workspace 路径安全和文件存在性；
- Artifact ID、digest、size、media type；
- owner Node、source Job/Attempt 和生成时间；
- provenance、lineage 和 `derived_from`；
- 同一 digest 的幂等登记；
- Research State revision 和引用完整性。

它不要求：

- 文件属于 Gaussian、XYZ 或 xTB 格式；
- 已经存在 parser；
- 已经存在 validator；
- 已经生成 `calculation_result.json`；
- 已经能够形成 Finding。

建议把当前不同含义的 Artifact 操作明确拆开：

| 操作 | 作用 |
| --- | --- |
| `artifact_register` | 登记 workspace、Job 或 remote collect 已经产生的文件 |
| `artifact_create` | 由文本/JSON/脚本输出创建一个新 Artifact |
| `artifact_read` | 按 Artifact ID 读取 manifest、excerpt 或结构化片段 |
| `artifact_derive` | 从已有 Artifact 生成 parsed/summary/plot 等派生 Artifact |
| `artifact_link` | 通过 Evidence Link 将 Artifact 连接到 Finding、Claim 或 Gate |

当前 `artifact_import` 既负责写文件，又要求 Gaussian/XYZ/xTB 等格式语义校验，重构后应作为兼容别名映射到 `artifact_create`。领域格式检查只能作为可选 Skill helper 或 `artifact_derive` 阶段；检查失败不能撤销已经登记的 raw Artifact。

也不能自动登记 workspace 中的每一个文件。Job collect 根据输出声明登记关键文件，Root Agent 或 Skill 显式登记其他文件，避免把缓存、临时文件和无关日志全部注入 Research State。stdout、stderr、scheduler receipt 和程序输出可以分别登记为不同 Artifact，并通过同一个 Attempt provenance 关联。

因此，重构的变化是 Artifact admission 更通用、来源更多、解析更可选；Artifact 的身份、digest、lineage 和 Research State 权威性保持不变。

### 4.6 Artifact、Finding 与 Research State 的对象边界

Artifact 是事实来源或证据载体，不是事实判断本身。它可以包含事实性数据，但不能因为文件存在就自动声称某个科学结论成立。Finding 是 Agent 或 Skill 对 Artifact 的解释，Claim 是研究中需要确认的命题，Evidence Link 则记录证据与 Finding、Claim 或 Gate 之间的关系。

它们的基本关系是：

```text
Node
  ↓
Attempt
  ↓
Artifact
  ↓
Evidence Link
  ↓
Finding
  ↓
Claim
  ↓
Gate
```

例如，`gaussian.out` 首先是一个 Raw Artifact；Root Agent 读取其中的终止信息后，可以创建“输出中出现正常终止标志”的 Finding；只有在适当的 parser 或 validator 存在时，才可以进一步把它表达为经过领域验证的计算结论。没有 parser 时，Artifact 仍然有效，Finding 需要在 provenance 中标明 `interpretation_mode` 和 `validation` 状态。

因此，Artifact 不是 Finding 的重复，也不是第二套科学状态。它是 Finding 和 Claim 可以追溯到实际文件、输出和数据的来源对象。Artifact 的 manifest、Attempt、Evidence Link、Finding、Claim 和 Gate 的引用关系由 Research State Runtime 统一管理；文件内容本身可以存放在 workspace 或对象存储中。

Research State Runtime 的完整职责范围包括以下几组对象：

| 对象组 | 对象 | 作用 |
| --- | --- | --- |
| Research Map | `phases`、`nodes`、`claims`、`claim_relations`、`findings`、`gates`、`focus` | 表达研究问题、工作项、命题、解释和判断条件 |
| Evidence and Execution | `attempts`、`artifacts`、`evidence_links`、`attempt_interpretations` | 记录执行过程、事实来源及其与研究语义的关联 |
| Workflow Control | `lifecycle_actions`、revision、`ChangeSet` | 提供事务、并发控制、恢复和状态演化 |
| Strategy Records | `strategy_plans`、`strategy_reviews` | 保存方法选择、计划和可选的审查意见 |

其中，Research Map 是研究语义图，Research State Runtime 是管理这张图以及证据和执行记录的完整运行时。Job Runtime 只负责执行和收集；它不能建立第二套 Artifact 注册表，也不能用 parser 成功与否覆盖执行事实。

对象之间的语义应保持以下边界：

```text
Artifact  = 实际产生或读取了什么
Finding   = 从证据中观察或解释出了什么
Claim     = 研究中要确认的命题
Research State = 管理它们的关系、版本和演化
```

这也是 Artifact 放入 Research State Runtime 的原因：它需要和 Finding、Claim、Attempt 共享 revision、引用校验和 provenance；但这不意味着把所有大文件内容复制进 Research State，也不意味着 Artifact admission 要承担领域科学验证。

### 4.7 Workspace 目录、Research Map 与执行数据

Workspace 是物理文件边界，Research Map 是逻辑研究图。两者必须关联，但不能互相替代：目录名和文件路径不能成为 Node、Claim 或 Finding 的事实来源；Research Map 也不应把所有脚本、日志和大文件内容复制进去。

推荐的 workspace 布局如下：

```text
workspace/
├── workspace_manifest.json       # workspace_id、map_id、根目录和版本
├── research_map/
│   ├── context.json              # Research State 的当前投影
│   ├── journal/                  # ChangeSet、revision 和恢复记录
│   └── snapshots/                # 可选的只读检查点
├── inputs/                       # 用户或 Root Agent 管理的项目输入
├── nodes/
│   └── <node_id>/
│       └── jobs/
│           └── <job_id>/
│               ├── request.json  # Job 请求和执行快照
│               └── attempts/
│                   └── <attempt_id>/
│                       ├── work/       # 实际执行 cwd，允许临时文件
│                       ├── staged/     # 本次执行的输入副本或链接
│                       ├── outputs/    # collect 前后的输出暂存
│                       ├── logs/       # 本地 transport 和 scheduler 日志
│                       └── receipt.json
├── artifacts/                   # 已登记 Artifact 的物理内容或本地缓存
├── memory/                      # bounded context 和会话记忆缓存
├── lifecycle/                   # Monitor、wake 和恢复记录
├── checkpoints/                 # Agent/Research State 检查点
├── operations/                  # 工具调用 receipt 和幂等记录
├── environments/                # 环境探测和连接配置快照
└── logs/                        # workspace 级日志
```

这些目录的语义边界如下：

| 目录 | 作用 | 是否是 Research Map 的权威来源 |
| --- | --- | --- |
| `research_map/` | 保存 Research State 当前投影、revision 和 journal；只能通过 Research State Runtime 修改 | 是（由 Runtime 统一管理） |
| `nodes/<node_id>/` | 为 Node 提供可读的工作和执行空间 | 否，目录由 `node_id` 导出 |
| `jobs/<job_id>/attempts/<attempt_id>/` | 保存一次 Job 请求及其重试执行现场 | 否，Attempt 记录在 Research State |
| `inputs/`、`artifacts/` | 保存输入和 Artifact 的物理内容 | 否，Artifact manifest 在 Research State |
| `memory/`、`lifecycle/`、`operations/`、`checkpoints/` | 运行时缓存、Monitor 和恢复数据 | 否，必要的状态摘要由 Runtime 记录 |

`nodes/<node_id>`、`jobs/<job_id>` 和 `attempts/<attempt_id>` 是稳定的路径约定，方便 Agent 和人类查找文件，但不能反向推断研究状态。一个 Node 可以有多个 Job 和多个 Attempt；一个 Artifact 也可以被多个 Finding、Claim 或 Node 引用。文件移动、重命名或清理不能直接改变 Claim、Finding 或 Node 状态，语义变更必须通过 `research_change`。

`research_map/context.json` 是给 Agent Context 和只读客户端使用的 bounded projection，不是 Root Agent 可以直接编辑的普通配置文件。Research State Runtime 负责把 ChangeSet 应用到权威状态并刷新 projection；任何目录扫描结果都只能作为外部观察，不能自动改写 Research Map。

`artifacts/` 不应再形成第二个 Artifact Registry。它只保存已经登记的 Artifact payload、本地 materialization 或缓存；Artifact 的 ID、digest、来源、lineage、producer Attempt 和引用关系仍由 Research State Runtime 统一登记和校验。对于大文件，可以只登记远程 URI 和 digest，并在需要 `artifact_read` 时按需 materialize，但必须明确其可访问性和缓存状态。

#### Local 与 Remote 的数据边界

Local workspace 所在的 Agent Server 是 Research State 的控制面和 canonical workspace。Remote 主机、容器或 scheduler 只拥有某个 Job/Attempt 的执行副本，不拥有独立的 Research Map，也不能直接修改 Claim、Finding 或 Gate。

`job_start` 生成一份不可变的 execution spec，其中包括：

- `workspace_id`、`map_id`、`node_id`、`job_id` 和 `attempt_id`；
- command、cwd、环境变量和资源参数；
- 要传输的 input Artifact ID 及其 digest；
- 脚本、配置和输出声明；
- remote backend、scheduler 和临时目录策略。

Remote adapter 按这份 spec 创建类似下面的执行目录：

```text
<remote_root>/tspi/<workspace_id>/<node_id>/<job_id>/<attempt_id>/
├── staged/       # 已校验的输入 Artifact
├── work/         # 远程程序 cwd
├── outputs/      # 声明的输出
└── receipt.json  # remote job/scheduler receipt
```

同步采用单向、按 Artifact 声明传输的策略：

1. **启动前**：Local 只上传 execution spec、Root/Skill 指定的脚本和 input Artifact，不默认镜像整个 workspace。Remote 写入后按 digest 校验，校验失败则 Job 不进入正常运行状态。
2. **运行中**：Monitor 只轮询 local process 或 remote scheduler 状态。stdout、stderr 和 scheduler receipt 可以按策略拉取尾部，但不会把远端任意文件持续同步进 Research State。
3. **收集时**：Remote adapter 根据 outputs 声明返回文件列表、大小、digest、退出状态和 scheduler receipt。Local 下载可用输出到 Attempt 暂存目录或 Artifact content store，重新计算 digest，验证通过后以一个 Research State ChangeSet 登记 Raw Artifact 并推进 Attempt 到 `collected`。
4. **部分结果**：某些输出缺失时，已下载且校验通过的输出仍然登记；collect 返回 `missing_outputs`，Attempt 保持 `collected`、`failed` 或 `unknown` 的正确执行状态，不丢弃已有 Artifact。
5. **网络中断**：无法确认远端状态时记录 `unknown`，Monitor 使用 workspace、job、attempt 和 remote receipt 做幂等 reconcile。不能因为一次连接失败就创建第二个 Attempt，也不能直接声称 Job failed。
6. **完成后清理**：成功收集并登记后，Remote workdir 可以按 retention policy 删除；Local Artifact 和 Research State provenance 保留。失败或 unknown 的远端目录按调试保留策略处理。

对于超大输出，Remote 可以把对象存储 URI、digest、大小和访问凭据引用作为 Artifact 的 materialization metadata 返回。此时 Research State 仍立即记录 Artifact 身份和来源，但只有在本地下载或远程读取能力可用后，Root Agent 才能把它作为可读证据使用。

同步的核心原则是：**Research Map 不同步，Job 数据按声明同步，Artifact 按 digest 登记，Remote 状态由 Monitor reconcile**。这样目录只是执行和存储布局，Research State 才是研究语义和证据引用的唯一权威。

### 4.8 Research Map Node 与 Node 目录的生命周期

Research Map 中的 Node 是研究工作项，不是文件夹。它至少描述标题、目标、所属 Phase、依赖的 Node、关联 Claim、Finding、Gate，以及当前状态和结果。Node 的创建属于 Research State 事务，由 Root Agent 通过 `research_change` 根据用户目标或研究计划显式创建。

典型生命周期是：

```text
创建 Research workspace / ResearchMap
        ↓
Root 分解研究目标
        ↓ research_change(create_node)
ResearchMap Node(state=planned)
        ↓
准备输入或启动 Job
        ↓
Node 目录按需物化，创建 Job/Attempt
        ↓
Attempt 产生 Artifact，Root 创建 Finding
        ↓
Node(active → closed)
```

因此，Node 的产生有两个不同时间点：

1. **语义产生**：`create_node` ChangeSet 成功提交时，Node 正式进入 Research State。此时它可以只有目标和计划，还没有任何文件、Job 或 Artifact。
2. **物理产生**：第一次需要输入、脚本、Job 或 Artifact 时，Runtime 创建 `nodes/<node_id>/` 及其下的 Job/Attempt 目录。这个目录是 Node 的 materialization，不是第二个 Node。

Node 目录也可以为了用户可读性在 `create_node` 后立即创建，但目录创建失败不能改变已经提交的 Research State；Runtime 应返回 materialization 错误，并在后续 Job 启动时重试。反过来，workspace 中手工创建的 `nodes/<node_id>/` 目录不能自动注册 Node，也不能自动改变 Node 状态。

两者的字段边界如下：

| 对象 | 存放内容 | 权威来源 |
| --- | --- | --- |
| Research Map Node | `id`、title、objective、phase、dependencies、claims、state、outcome | Research State Runtime |
| Node 目录 | 输入文件、脚本、Job 请求、Attempt 工作目录、输出暂存和日志 | workspace 文件系统 |
| Attempt | 一次执行的状态、环境、输入/输出 Artifact 引用和 receipt | Research State Runtime |
| Artifact | 文件身份、digest、来源、lineage 和物理位置 | Research State Runtime；payload 在 workspace/对象存储 |

短时探索性的 `bash`、`read`、`write` 不需要强制创建 Node。只有需要进入 Research State、关联长时间 Job 或作为研究证据保存时，Root 才创建 Node、Attempt 或 Artifact。`job_start` 在研究模式下要求引用一个已经存在的 `node_id`；它不能隐式创建一个缺少目标和语义的 Node。

Remote 上的目录也不是新的 Node：

```text
Local ResearchMap: node_abc
Local Attempt:     attempt_123
Remote directory:  .../node_abc/job_xyz/attempt_123/
```

Remote adapter 使用同一个 `workspace_id`、`node_id`、`job_id` 和 `attempt_id`，只创建执行副本。Remote 不维护自己的 Research Map，也不直接创建 Node、Finding 或 Claim；执行结果通过 collect、digest 校验和 Research State ChangeSet 回到 Local。

### 4.9 Node 的创建判定与继续执行规则

Node 不应由 Runtime 根据目录、文件、Job 或 Artifact 自动推导。它代表一个需要在 Research State 中独立跟踪的研究目标，是 Root Agent 对研究问题进行分解后的语义决定。Agent 是否创建 Node，应由当前用户意图、Research State focus 和已有 Node 的目标共同决定，而不是由某个程序是否运行来决定。

当前 `create_node` 的技术最低要求是：唯一的 `id`、非空的 `title` 和非空的 `objective`；可选的 `phase_id`、`claim_ids` 和 `dependency_ids` 必须引用已经存在的对象。重构后还应要求 Root 在创建 Node 时给出可审计的语义信息（可以放在 metadata 或计划记录中）：

- 为什么当前目标不能由已有 Node 继续承载；
- 这个 Node 的预期交付物或可观察结果；
- 它关联或验证的 Claim；
- 它依赖哪些 Node，以及完成条件是否需要 Gate。

这些是 Agent 的规划要求，不应被内核固化成 Gaussian、化学或其他领域字段。Research State Runtime 负责检查引用、ID 唯一性、依赖环和状态转换；Root Agent 负责判断两个目标是否是同一个研究工作项。

Root 每次恢复或开始一个 turn 时，应先读取当前 bounded research context：

```text
focus.node_ids / focus.claim_ids
开放的 planned、active、paused、blocked Node
Node 的 objective、依赖、Finding、Gate 和 Attempt 摘要
最近一次 Job/Attempt 状态和待处理的 lifecycle_action
```

默认决策顺序是：

1. **继续当前 Node**：当前 focus 有 active 或 planned Node，且用户请求仍服务于该 Node 的 objective。Root 继续使用这个 `node_id`，需要重新执行时创建新的 Job/Attempt。
2. **创建新的 Attempt**：目标没有变化，只是重试、换环境、修复输入、调整资源、重复计算或比较同一 Node 目标下的执行条件。Node 不变，Attempt 变新，并在 metadata 中记录变化。
3. **创建新的子 Node**：用户目标被拆成一个需要独立跟踪、独立证据和独立完成条件的子目标。新 Node 通过 `dependency_ids` 或关联 Claim 连接到原 Node。
4. **创建新的并列 Node**：目标、范围、交付物或判断标准已经改变，继续写入原 Node 会混淆其生命周期或结论来源。
5. **恢复已关闭 Node**：不允许通过普通状态转换重新打开 `closed` Node。若用户提出新的问题，应创建新的 Node，并通过 Claim、dependency 或 metadata 记录与旧 Node 的关系。

可以用下面的判断表约束 Agent 的行为：

| 当前变化 | 继续原 Node | 新 Attempt | 新 Node |
| --- | --- | --- | --- |
| 程序失败后重试 |  | ✓ |  |
| 修改输入以完成同一目标 |  | ✓ |  |
| 更换计算环境或资源 |  | ✓ |  |
| 同一目标下比较多个方法 | 通常 | ✓ | 需要独立结论或独立 Gate 时 |
| 研究问题或交付物改变 |  |  | ✓ |
| 原 Node 已关闭且出现新问题 |  |  | ✓ |
| 将一个大目标拆成独立步骤 | 保留父 Node |  | ✓（子 Node） |

因此，系统不应试图通过字符串相似度自动决定“是不是同一个 Node”。它应让 Root 读取上下文、明确选择 `node_id`，或者提交 `create_node` 与 `set_focus` 的 ChangeSet。若请求缺少足够信息，Root 可以先继续当前 focus，并把需要拆分的理由记录为 lifecycle action 或 IssueFinding，而不是无依据地创建大量 Node。

### 4.10 Research Map 的核心：假设、证据与修订闭环

Research Map 不能只是 Node、Job 和文件的索引。Research Agent 与普通 coding agent 的关键区别，是它必须围绕假设提出可检验的预测，收集证据，形成观察，评估假设，并在证据不足或矛盾时修订假设。Job 和 Artifact 是这个闭环的执行与证据部分，不能代替闭环本身。

目标循环是：

```text
研究问题
    ↓
Claim（假设/命题）
    ↓ predictions / falsifiers
Node（检验或收集证据的研究工作项）
    ↓
Attempt（一次执行）
    ↓
Artifact（原始或派生证据）
    ↓
Finding（观察或解释）
    ↓ evidence link + claim assessment
Claim: supported / contradicted / inconclusive
    ↓
保留、细化、否定或创建修订后的 Claim 和下一项 Node
```

对象边界应保持如下：

| 对象 | 在研究循环中的含义 | 典型变化 |
| --- | --- | --- |
| `Claim` | 尚待支持或反驳的假设、命题或研究判断 | 由 proposed 进入 supported、contradicted 或 inconclusive；原命题修订时保留历史 |
| `predictions` / `falsifiers` | Claim 对可观察结果的预期和反驳条件 | 指导 Node 和 Gate 的设计 |
| `Node` | 为检验 Claim 或解决问题而安排的独立研究工作项 | planned、active、blocked、closed |
| `Attempt` | 一次具体执行或实验尝试 | 可重试、可更换环境和参数 |
| `Artifact` | 实际产生或读取的数据 | raw、derived、materialized |
| `Finding` | 从 Artifact 中提取的观察、测量或问题 | open、confirmed、resolved、superseded |
| `EvidenceLink` | 证据对 Finding、Claim 或 Gate 的支持、反驳或限定关系 | supports、contradicts、qualifies、documents |
| `Gate` | 对 Node 或 Claim 的明确完成/判断条件 | pass、fail、inconclusive、blocked |

当前模型已经有 Claim status、predictions、falsifiers、Finding、EvidenceLink 和 Gate 这些基础构件，但仍存在研究闭环缺口：

1. `set_claim_status` 可以直接改变 Claim 状态，没有强制要求证据、理由和输入 revision。
2. `create_finding` 当前允许没有 `source_refs`，而 `fact` 默认是 `confirmed`；这容易把 Agent 的一句推断误写成事实。
3. Claim 没有一等的 assessment 历史，也没有清晰区分“评估旧 Claim”和“提出修订后的新 Claim”。
4. Finding 同时承担原始观察和解释结论，`provenance`、验证状态和解释方式需要成为明确字段。
5. Research Context 没有把“尚未检验的预测、未解决的 Claim、失败的 Gate 和下一步义务”投影给 Root，Agent 只能看到对象列表，无法稳定地进行研究推进。

重构后应采用以下规则：

- `create_claim` 创建的是待检验命题，不代表结论成立；`predictions` 和 `falsifiers` 是推荐字段，具体内容由 Root 或 Skill 根据领域填写。
- `create_finding` 对 `fact` 至少要求已登记的 source Artifact 和 provenance。`confirmed` 只表示该观察已与来源内容核对，不表示它已经证明了 Claim。
- Claim 的支持或反驳通过独立的 `assess_claim` ChangeSet 记录，包含 `claim_id`、verdict、evidence_refs、reason、actor 和 `input_revision`。Claim 当前 status 是这些 assessment 的最新投影。
- Claim 文本不能被静默覆盖。修订时创建新的 Claim，通过 `revises`、`refines` 或 `supersedes` 关系连接旧 Claim；旧 Claim 保留原有证据、评估和历史状态。
- Finding 可以先记录“观察到什么”，再由 Root 通过 EvidenceLink 和 Claim assessment 决定“这对哪个假设意味着什么”。没有 parser 时也可以形成有明确 `validation=unavailable` 的观察。
- Claim status 不能因为 Job 成功、parser 成功或 Finding 创建而自动改变。只有 Root 在证据和上下文基础上明确提交 assessment，Claim 才会改变。

Research Memory 应从 Research State revision 构造一个 `research_obligations` 投影，至少包含：

- 当前 focus 下尚未检验的 Claim predictions/falsifiers；
- proposed、inconclusive 或 contradicted 的 Claim；
- 没有足够来源或仍待解释的 Finding；
- 未通过或未评估的 Claim/Node Gate；
- lifecycle action 指定的 inspect、launch、analyze、evaluate、review 或 close 动作。

Root Agent 每次恢复时先读取这些 obligations，再决定继续当前 Node、创建 Attempt、创建子 Node、提出新 Claim，还是修订旧 Claim。Runtime 负责引用完整性和状态转换，Root 负责科学假设、证据解释和研究方向；Monitor、Job Runtime 和 parser 都不能代替这个判断。

一个完整的研究推进示例如下：

```text
Root 创建 Claim C1：方法 A 预测结构 X 比结构 Y 更稳定
Root 创建 Node N1：生成 X/Y 的可比计算结果
Root 启动多个 Attempt，收集 Artifact
Root 创建 Finding F1：Y 的能量低于 X，source_refs=[art_result]
Root assess_claim(C1, contradicted, evidence_refs=[art_result])
Root 创建修订 Claim C2：在当前溶剂模型和基组下，稳定性排序依赖构象
Root 创建 Node N2：检验构象和溶剂模型影响
```

这个闭环才是 Research Map 存在的核心；Node、Attempt、Artifact 和 Finding 都应服务于假设的提出、检验和修订，而不是把 Research State 变成计算任务目录。

### 4.11 研究闭环如何进入 Agent Loop

“假设—证据—修订”不是一个替换 Pi 的新事件循环，也不是由 Job Runtime 自动执行的固定状态机。它由三部分共同实现：

1. **Core Research Skill 提供方法规则**：告诉 Root 什么时候应提出 Claim、如何写 prediction/falsifier、什么时候继续 Node 或创建新 Node、如何把 Artifact 解释成 Finding、何时评估或修订 Claim。
2. **Research Memory 提供当前研究义务**：在每个 turn 开始时，把 focus、开放 Claim、未检验 prediction/falsifier、待解释 Finding、Gate 和 lifecycle action 放入 bounded context。
3. **Research State Runtime 提供不可绕过的不变量**：通过 `research_change` 的 ChangeSet 校验 Artifact 引用、EvidenceLink、Claim assessment、revision、Node 状态和并发 revision。它不替 Root 选择科学假设，但会拒绝结构不合法或不可追溯的状态变更。

每个普通 turn 的实际流程仍然是 Pi loop：

```text
Research Memory.snapshot(revision)
    ↓
Core/Domain Skill + conversation + research_obligations
    ↓
Pi model turn
    ↓
Root 调用 read/write/bash、job_*、artifact_*、research_*
    ↓
Research State Runtime 应用 ChangeSet 或 Job Runtime 返回 receipt
    ↓
更新 revision / liveness / context
    ↓
继续当前 turn，或 checkpoint 等待下一次唤醒
```

长任务只改变 turn 的暂停和恢复方式：

```text
Root → job_start
    → checkpoint(waiting_external)
    → Pi turn 暂停
    → Monitor poll/reconcile
    → 同一个 workspace/session wake
    → Root 读取 obligations 和 Job 状态
    → job_collect → artifact_read
    → create_finding → assess_claim/revise_claim
```

没有长任务时，所有步骤都可以在连续的普通 Pi turns 中完成。没有 parser 时，Root 仍可用 `artifact_read`、`bash` 或 Skill helper 读取原始 Artifact 并创建带 provenance 的 Finding；Research State Runtime 不会自动把它变成 supported Claim。

Core Skill 只提供研究方法和决策提示，不能单独保证闭环完整。因此以下内容必须由 Runtime 保证：

- Claim assessment 具有 evidence_refs、reason 和 input revision；
- fact Finding 的来源和 provenance 可追溯；
- Claim revision 不覆盖旧 Claim；
- Job 成功、parser 成功或 Finding 创建不会自动改变 Claim status；
- Monitor 唤醒同一个 Root session，不启动新的研究决策者；
- Research Memory 每次从最新 Research State revision 构造，而不是依赖 Agent 自己记住上一轮假设。

以下内容由 Root Agent 根据 Core/Domain Skill 决定：

- 是否值得把一个问题写成 Claim；
- prediction 和 falsifier 如何表述；
- 证据是否支持、反驳或限定 Claim；
- 是创建新的 Attempt、Node、Claim revision 还是结束当前研究分支；
- 哪些观察足以形成 Finding，哪些只保留为 Artifact。

这保留了 coding agent 的开放性：Root 仍可自由组合 `write`、`bash`、`read` 和 `job_*`。Research State 增加的是可追溯的研究语义和事务约束，而不是把所有科学方法预编译成固定 capability 或固定执行流程。

## 5. 公开工具设计

### 5.1 `job_start`

```json
{
  "nodeId": "node_1",
  "command": ["g16", "input.gjf"],
  "cwd": "nodes/node_1/jobs/job_123",
  "inputArtifacts": ["art_input"],
  "outputs": ["gaussian.out", "checkpoint.chk"],
  "environment": "local",
  "timeoutSeconds": 86400,
  "monitor": "wake"
}
```

这里的 `cwd` 是 Job 请求中的逻辑工作目录；Job Runtime 会将它解析到对应的 `attempts/<attempt_id>/work/`，并把 staged input 放入同一 Attempt 目录。Root Agent 不需要提前知道由 Runtime 分配的 Attempt ID。

返回：

```json
{
  "jobId": "job_123",
  "attemptId": "attempt_1",
  "status": "submitted",
  "monitorId": "mon_...",
  "nextAction": "wait_for_monitor"
}
```

它立即返回，不等待程序完成，也不调用 parser。

### 5.2 `job_status`

返回 Job、Attempt、scheduler 状态、最近事件和是否可以 collect。查询失败时区分 `unknown` 与 `failed`，不擅自把 unknown 当作失败。

### 5.3 `job_collect`

收集声明的输出、stdout、stderr、状态文件和 scheduler receipt，生成 Artifact manifest，并把 Attempt 至少推进到 `collected`。某个输出缺失时返回部分结果和缺失列表；不能丢弃已经存在的输出。

### 5.4 `job_cancel`

向 local/remote adapter 发送取消请求，记录 receipt。取消请求本身失败时 Attempt 进入 `unknown` 或保持 active，等待 Monitor reconcile。

### 5.5 `artifact_register`

通用登记接口，支持：

- workspace 内已有文件；
- Job collect 产生的输出；
- Root Agent 写入的 JSON、CSV、脚本或日志；
- Skill helper 生成的 derived artifact。

`format`、`kind`、`role` 可以是 annotation。领域 validator 可以附加 metadata，但不是 admission gate。

### 5.6 `artifact_read`

提供 bounded text excerpt、JSON path、line range、manifest 和 digest。大文件不直接进入模型上下文。

### 5.7 `compute_readiness` 的替代

优先删除作为 Agent-facing 工具的 `compute_readiness`。需要预检时提供通用：

```text
job_probe(command, environment)
```

只检查命令、工作目录、远端连接、scheduler 和资源配置。它返回 probe 结果，不返回“科学 capability ready”。Skill 可以选择调用，也可以直接启动 Job 处理真实错误。

### 5.8 `research_change`

保持 ChangeSet 事务语义，但扩展通用 Artifact admission 和 Evidence Link 操作。它不要求 `parser_facts`，不要求 `calculation_result.json`，不把 Finding candidate 作为 compute 的隐式副作用。

## 6. Extension 和 Skill 重构

### 6.1 新 manifest 重点

建议 Extension manifest 只声明 bundle 身份和 Skill 根目录；Skill 内部资源由 Skill loader 递归计算 digest：

```json
{
  "schema_version": "tspi-extension/2",
  "name": "chemical",
  "version": "2.0.0",
  "skills": [
    {"name": "gaussian", "path": "skills/gaussian", "digest": "sha256:..."}
  ]
}
```

每个 Skill 的 digest 覆盖它自己的 `SKILL.md` 及其相对资源目录；`scripts`、`templates` 和 `analyzers` 不再作为 Extension 全局 helper 清单暴露。旧 `providers` 可以继续被 loader 读取，但只能标记为 `compatibility` 或 `optional`，不能成为 Job 执行前置条件。

### 6.2 Gaussian Skill

Gaussian Skill 应直接描述：

1. 如何使用 `write` 生成 `.gjf`；
2. 如何确认 charge/multiplicity、route section 和输入 geometry；
3. 如何用 `job_start` 提交 `g16`；
4. 如何用 `job_collect` 登记 `.out`、`.chk`、stdout/stderr；
5. 如何用 `artifact_read` 或 Python helper 检查正常终止、SCF、优化、频率、IRC 等；
6. 哪些观察可以形成 FactFinding，哪些只能作为 IssueFinding；
7. 如何把 parser/helper 的版本写入 derived Artifact provenance。

Gaussian 没有 parser 时，步骤 1–4 仍然有效，步骤 5 可以由 Agent 直接组合 `read` 和 `bash` 完成。

### 6.3 Script Skill

`extensions/scripting` 不提供新的执行能力，也不要求 `script.bash@1` provider。Skill 只规定：

- 脚本由 Root Agent 写入 workspace；
- 使用 `job_start` 而不是 `bash sleep` 等待长任务；
- 输出文件由 `job_collect` 登记；
- 结果 JSON 只是普通 Artifact；
- 是否把结果解释成 Finding 由 Root Agent 决定。

## 7. 各模块的目标职责和代码迁移

| 当前路径 | 目标处理 | 迁移结果 |
| --- | --- | --- |
| `apps/app-server/pi-native-compute.mjs` | 拆为 `pi-native-job.mjs`，只做 Job tool adapter、receipt、Attempt 调用和 Monitor staging | 保留薄适配层，删除 Compute subagent/task packet 调用 |
| `packages/agent-runtime/agents/compute/*` | 删除或迁移为 `job-execution-journal` | 不再启动模型 Harness；journal 记录 Job action 即可 |
| `packages/research-compute/research_compute/control.py` | 拆为 `job_control.py`、`job_collect.py`、`job_reconcile.py` | 不再有强制 parse terminal stage |
| `research_compute/provider.py` | 改名 `execution_adapter.py` | 只定义 local/remote transport adapter；删除 classify/parse/validator 必选接口 |
| `research_compute/capabilities.py` | 改成可选 `skill_inventory.py` 或兼容 catalog | 不作为 execution gate；只提供发现和文档关联 |
| `research_compute/readiness.py` | 改成 `job_probe.py` | 只做 executable、cwd、remote/scheduler probe |
| `research_compute/task_validation.py` | 移到 extension helper 或 `artifact_validation.py` | 缺失 validator 不阻止 collect |
| `research_compute/artifacts.py`、`artifact_registry.py` | 提取通用 `artifact_manifest.py` 和 `artifact_admission.py` | 支持未知格式 raw Artifact |
| `apps/app-server/pi-native-tools.mjs` | 增加 job/artifact 原语，保留 research 工具 | 删除 compute-specific parse 组装 |
| `apps/app-server/server-tools/core-tools.mjs` | 暴露 Job、Artifact、Research State、Monitor 相关工具 | 不再加载领域 provider 才能执行普通 Job |
| `apps/app-server/extension-manifest-loader.mjs` | 发现 bundle、Skill 根目录并计算 Skill 资源 digest | provider 改为 optional metadata |
| `packages/research-state/research_state/operation_registry.py` | 增加 `register_artifact`、`create_evidence/link_evidence`、`assess_claim`、`revise_claim` 的公开合同 | raw Artifact 和假设评估都走规范 ChangeSet |
| `packages/research-state/research_state/agent_workspace.py` | 保留事务和引用校验，删除 parser 前置条件；增加 Claim assessment/revision 历史 | Finding 需要可追溯来源，Claim 状态不能无证据静默改变 |
| `packages/research-memory` | 保持 | 增加 Job/Artifact summary 的 bounded projection |
| `packages/research-compute/research_compute/workspace/monitor.py` | 改为 generic Job Monitor records | 与 backend 类型解耦 |
| `apps/app-server/pi-monitor-worker.mjs` | 保持 worker 机制，调用 generic job reconcile | 不执行 finalize/parse |
| `apps/agent-cli/compute.py` | 改为 `job.py`，保留旧命令兼容映射 | `compute_run` 进入 deprecation 阶段 |
| `extensions/chemical/providers/*` | parser、输入生成和分析迁移到 `extensions/chemical/skills/*/scripts`、`analyzers` 或 optional library | 现有科学代码可复用，但不再阻止 Job |
| `extensions/script/providers/*` | 删除整个 script compute provider；可选脚本说明迁移到 `extensions/scripting/skills/scripting/` | Agent 直接调用 `bash`/`job_start` |
| `packages/tspi-provider-runtime` | 保留给 optional deterministic analyzers | 不参与基础执行 |
| `packages/agent-runtime/agents/review/*` | 保持 advisory child agent | 不是研究推进的必要步骤 |

## 8. 生命周期和典型流程

### 8.1 短命令

```text
Root write input.json
Root bash python validate_input.py input.json
Root artifact_register validation.json
Root research_change(create_finding/source_refs)
```

没有 Job Runtime 参与也可以完成。

### 8.2 长时间 Gaussian

```text
Root research_read(context)
Root 显式读取 gaussian Skill
Root write input.gjf
Root artifact_register(input.gjf)
Root job_start(g16 input.gjf)
Agent Server 返回 job_id/attempt_id/monitor_id
Root research_checkpoint(waiting_external)
Monitor poll
Monitor delivery -> same session wake
Root research_read(liveness/context)
Root job_status(job_id)
Root job_collect(job_id)
Research State 登记 gaussian.out/stdout/stderr/chk
Root artifact_read(gaussian.out excerpt)
Root bash/helper 解析（可选）
Root artifact_register(parsed-summary.json)（可选）
Root research_change(create_finding / create_evidence)
Root research_checkpoint(continue_required/terminal)
```

### 8.3 没有 parser

```text
job_collect = succeeded
raw output Artifact = registered
parser = unavailable
validation = unavailable
Finding = 可以由 Root 基于 raw Artifact 创建
claim status = 由 Root 明确决定，不能自动改变
```

### 8.4 Root Agent 生成新程序

```text
Root write run.py
Root job_start([python, "run.py"], outputs=["result.json"])
Monitor wake
Root job_collect
Root artifact_read(result.json)
Root research_change(...)
```

不需要新增 provider、descriptor、capability catalog 或内核代码。

## 9. 迁移策略

### Phase 0：冻结基线和不变量

- 标记当前工作树中的已有改动，建立重构分支和审计记录。
- 增加回归测试，先固定以下行为：workspace/session 绑定、Research State revision、Monitor delivery 幂等、Artifact digest、remote unknown 状态。
- 暂不删除旧 `compute_run`。

### Phase 1：引入通用 Job Runtime

- 新增 `job_start/status/collect/cancel` 内部接口和 schema。
- local adapter 先复用 `local_lifecycle.py`，remote adapter 复用 scheduler/broker。
- Job 只生成 Attempt、操作 receipt 和 raw output manifest。
- `compute_run` 暂时作为兼容 wrapper，内部调用 Job Runtime。

### Phase 2：解耦原始 Artifact admission

- Research State 增加 raw Artifact 的规范注册操作。
- `job_collect` 在 collect 成功后直接注册原始输出。
- parser、validator 和 `calculation_result.json` 变成可选 derived stage。
- 增加 `collected` Attempt 状态及对应 liveness 语义。

### Phase 3：把 Skill 变成实际流程入口

- 重写 core/orchestration、core/research-state、Gaussian、xTB、PySCF 和可选 scripting Skill。
- Skill 使用 `write`、`bash`、`job_*` 和 `artifact_*`。
- `package.json` 的 Pi Skill 清单迁移到 `extensions/core/skills/` 和各 Extension Skill 根目录；默认 Pi tools 保持 `read`、`bash`、`edit`、`write`，`grep`、`find`、`ls` 按需启用。
- 将 provider 中的输入生成、解析和验证代码迁移为 helper/analyzer，保留原测试。
- capability catalog 只作为兼容发现接口，不再阻止未知 Job。

### Phase 4：移除 Compute 子 Agent

- `pi-native-compute.mjs` 改成 `pi-native-job.mjs`。
- 删除 task packet、fixed action plan、`compute_result` 和模型 Harness 启动路径。
- 原 action journal 改成 Job action receipt，保留恢复和审计能力。
- 更新 `packages/agent-runtime/host-api/lifecycle.mjs`，不再为 `compute_run` 建 child-agent phase。

### Phase 5：重定位 readiness 和 extension provider

- `compute_readiness` 改成可选 `job_probe`，旧接口返回 deprecation 信息。
- extension manifest v2 以 bundle 身份和 Skill 根目录为核心；helper/analyzer 只作为 Skill 内部资源。
- provider descriptor 继续读取一段时间，但不再作为执行门禁。
- 无 parser 的 extension 仍必须能执行和收集输出。

### Phase 6：清理旧协议

- 删除 `classify_task`、`required_artifacts`、`parser_name`、`validate_parsed_task` 等核心必选接口。
- 删除 capability-specific `finalize → parse` 固定链。
- 将 `compute_run` 标记为兼容别名，最终只保留 `job_*`。
- 更新文档、安装包 inventory、contract tests 和 release checks。

## 10. 测试和验收标准

### Unit/contract

- 任意 command vector 可以创建 Job，不需要 capability descriptor。
- 任意文本、JSON、CSV、脚本输出都可以登记 raw Artifact。
- Job Runtime 不导入 chemical extension。
- parser/validator 缺失不会阻止 collect。
- `create_finding` 只要求 source Artifact 已登记。
- `compute_readiness` 或 `job_probe` 不产生 Attempt、Artifact 或 Finding。
- Job action journal 可恢复、幂等且不能伪造 scheduler 状态。
- Claim assessment 必须引用可解析的 Evidence/Artifact，或明确记录为暂时的 Root interpretation；不能仅凭 Job 成功自动把 Claim 标为 supported。
- Claim revision 保留旧 Claim、assessment 和证据，并通过 `revises`/`refines`/`supersedes` 关系连接新 Claim。
- 没有 source Artifact 的 fact Finding 被拒绝，或必须显式标记为未验证的中间观察。
- Research Memory 能投影未检验 predictions、falsifiers、开放 Claim、失败 Gate 和 lifecycle obligations。
- 连续 Pi turns 可以完成“创建 Claim → 创建 Node → 运行 Job → 登记 Artifact → 创建 Finding → assess Claim → 创建修订 Claim”的闭环。
- Monitor wake 后仍由同一个 Root session 继续 Claim assessment，不能创建第二个隐式研究 Agent。

### Integration

1. Root 用 `write + bash` 生成并运行一个新 Python 程序，不安装 extension。
2. fake Gaussian executable 成功退出但没有 Gaussian parser，仍能：
   - 创建 Attempt；
   - 收集 `gaussian.out`；
   - 注册 raw Artifact；
   - 由 Root 创建带 source ref 的 Finding。
3. parser 存在时能生成 derived Artifact，但 parser 失败不删除 raw Artifact。
4. validator 缺失时记录 `validation=unavailable`，不改变 execution state。
5. local Job、remote scheduler Job、unknown submit、cancel 和 crash recovery 都能被 Monitor reconcile。
6. Monitor worker 重启不会重复 wake，也不会启动第二个 Agent loop。
7. Research State revision conflict 不会重复登记 Artifact 或 Finding。
8. Review 子 Agent 只能产生 advisory result，不能直接写 ResearchMap。

### 验收命令和环境

所有测试环境必须安装到 `/home/iaw/debug/tspi-test-env`，Python 和依赖也使用该目录。启动的 Agent Server、Monitor、Relay 或 scheduler fake 服务必须在测试结束后停止并删除。单元、Node 和 contract 测试可以并行运行；live remote test 必须单独清理远程作业。

## 11. 风险和处理

### 任意命令的可追溯性

取消 capability gate 后，Job provenance 必须记录完整 argv/脚本 digest、cwd、输入 Artifact、环境摘要、Skill digest、开始结束时间和输出 digest。这样任意命令仍然可审计。

### 任意命令的执行安全

安全模型应沿用 coding agent 的 bash/Agent Server 执行边界。这个重构不新增领域 permission gate，也不让 Skill 获得超过 Root Agent 原有 shell 的权限。Agent Server 仍然负责 workspace 绑定、进程生命周期、超时和远端 transport。

### 领域解析质量

内核不保证科学解析质量。它只保证原始证据不丢失、来源可追溯、Agent 不能把“未验证”写成“已验证”。解析质量由 Skill、helper、Review 和 Root Agent 的研究判断承担。

### 兼容性

先通过 `compute_run` 到 `job_*` 的 wrapper 迁移，保持旧客户端能查询 Attempt 和 Monitor；新 Skill 只使用新接口。旧 capability/provider 记录保留为 metadata，直到所有旧测试和扩展迁移完成。

## 12. 最终架构判定

重构完成后，TSPi 的内核应该只回答这些问题：

- 当前 workspace/session 是谁？
- 这个命令或 Job 的生命周期是什么？
- 输出文件在哪里，digest 是什么，是否已经登记？
- Research State 的 revision、引用和状态转换是否合法？
- 外部 Job 是否有新的事件，需要唤醒哪个 session？

内核不应该回答这些领域问题：

- 这是 Gaussian 还是另一个程序？
- 这个输入属于优化、频率还是 IRC？
- 输出中是否存在频率？
- SCF 是否收敛？
- 这个结果是否足以支持 Claim？

这些问题属于 Skill、辅助脚本、可选 analyzer 和 Root Agent 的研究推理。这样系统才真正成为“带有 Research State、Research Map 和 durable Monitor 的 coding agent”，而不是“只能调用已注册科学 provider 的计算工作流引擎”。
# 实施状态

本文保留重构前后的决策记录。计划中的兼容 facade、旧 Compute/Review
入口和 provider registry 已在最终实现中删除；当前运行时只提供 Job Runtime、
Artifact Store、Research State 和 Skill 指令路径。文中的旧名称仅用于说明迁移背景。
