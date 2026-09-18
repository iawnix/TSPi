---
name: tspi-orchestration
description: 通过统一的 ResearchMap、研究命令和计算命令编排 TSPi 研究任务。
---

# TSPi 研究编排

[English version](SKILL.md)

当任务需要改变研究计划、解释科学结果或查询项目进展时使用本 Skill。
一个项目只有一个规范的 `ResearchMap`。它是由类型化对象组成的数据结构，包含
`ResearchPhase`、`ResearchClaim`、`ResearchNode`、`Finding`、`Gate`，以及
Claim 关系、焦点和 revision。TS Web 与 Root 直接读取同一份 map，不维护第二套
投影。

Research Kernel 负责 map 的校验、引用、revision 和原子变更；它不选择科学方法，
也不运行软件。Compute environment、Attempt 和 Artifact 是 Node 使用的运行记录，
不是另一套研究状态模型。

## 研究循环

1. 用 `ts_state mode=summary` 或 `mode=map` 读取当前 map。只有确实需要时才使用
   `detail`、`locate`、`artifacts`、`capabilities`、`runs`。`/research` 提供同样的
   研究读取；`/compute` 和 `ts_environment` 查询本地与远端计算环境。
2. 明确一个研究问题及其不确定性，创建或复用 Phase、Claim 和一个有边界的
   Node。Phase 只用于把相关 Node 分组导航，不承担生命周期。Node 状态是
   `planned`、`active`、`paused`、`blocked`、`closed`；关闭时结果是
   `completed`、`inconclusive` 或 `stopped`。
3. 加载相应领域 Skill，选择有边界的方法，在所属 Node 下运行。计算和生成文件
   必须绑定逻辑 Artifact ID。
4. 先检查原始产物再写结论。Node 对已核验事实产出 `FactFinding`，对异常、限制、
   冲突或未决问题产出 `IssueFinding`。Finding 属于 map，原始日志不属于 map。
5. 只有需要明确收尾或评估标准时才创建 `Gate`。Node 的 Gate 使用 `scope=node`，
   Claim 的 Gate 使用 `scope=claim`；评估结果为 `pass`、`fail`、`inconclusive`
   或 `blocked`。
6. 在检查事实和未解决问题后更新 Claim 状态（`proposed`、`supported`、
   `contradicted`、`inconclusive`、`withdrawn`）和 Node 状态。Node 要以
   `completed` 关闭时，已有的 NodeGate 必须先通过。

## 规范写入

所有 map 变更都通过 `ts_change`。先用 `ts_state mode=operations` 查询实时操作目录，
并严格使用返回字段。当前的小型操作集是：

```text
create_phase       create_claim       create_node
create_finding     create_gate        evaluate_gate
set_node_state     set_claim_status   relate_claims
set_focus
```

每个操作都是一个 `ChangeSet` 中的显式项。新对象使用项目内新 ID，已有对象只使用
map 返回的 ID，不能猜测已有 ID。提交时带简短 rationale；在并发或可能过期时带
`expected_revision`，有来源时带 `basis_refs`。Kernel 会在隔离副本上校验后一次提交
新的 map revision，失败不会留下半个变更。

保持模型轻量：Node 产出只使用 FactFinding 和 IssueFinding，有限评估使用 Gate
criteria/evaluations，不再引入第二套证据协议。计算或 Review 的结果只有经
Root 通过 `ts_change` 记录后才成为研究状态。

## 计算与恢复

选择计算前用 `ts_state mode=capabilities capabilityKind=compute`，查询注册分析时用
`capabilityKind=analysis`。用 `mode=artifacts` 找到 Node 所属产物，用 `mode=runs`
查看持久化执行历史。`ts_environment`（或 `/compute`）同时覆盖本地和远端 profile；
远端只是 environment 的一种类型，不是另一套公开 API。调度器、传输、程序、解析和
收集错误先作为运行证据处理，只有核对原始产物后才把科学后果记录为 IssueFinding。

`ts_review` 只提供建议。读取 dossier，用 `ts_reply` 回应，再通过 `ts_change` 记录
Root 的解释。保留失败或不确定的 Node；问题或交付物改变时创建依赖 Node。

## 参考路由

按当前任务只读取需要的参考：

| 需要 | 参考 |
| --- | --- |
| 术语 | [glossary.md](references/glossary.md)、[glossary.zh-CN.md](references/glossary.zh-CN.md) |
| map 模型与持久化 | [state_model.md](references/state_model.md)、[workspace_contract.md](references/workspace_contract.md)、[pathway_model.md](references/pathway_model.md) |
| ChangeSet 字段与提交规则 | [decision_contract.md](references/decision_contract.md)、[agent_decision_protocol.md](references/agent_decision_protocol.md) |
| 计算与分析工具 | [compute_tools.md](references/compute_tools.md)、[artifact_tools.md](references/artifact_tools.md)、[backend_contract.md](references/backend_contract.md) |
| 环境与失败处理 | [remote_contract.md](references/remote_contract.md)、[runtime_environment.md](references/runtime_environment.md)、[program_runtime_failures.md](references/program_runtime_failures.md) |
| Root/Pi 集成 | [pi_agent_adapter.md](references/pi_agent_adapter.md) |
| 源码策略 | [package_sources.md](references/package_sources.md) |
| 渲染 | [渲染接口](../tspi-render/references/render_contract.md) |
| 报告 | [报告模板](../tspi-report/references/report_template.md) |
| 通知 | [邮件投递](../tspi-email/references/email_delivery.md) |

过渡态搜索、xTB/CREST、Gaussian、连通性、机理、渲染、报告和邮件任务分别使用对应
的领域 Skill。
