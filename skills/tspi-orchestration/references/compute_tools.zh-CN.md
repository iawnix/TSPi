# Compute 子 Agent 与类型化动作

`compute_run` 委派一个有边界的运行生命周期。Root 选择化学问题、方法、ResearchNode、输入、
参数和执行目标。Host 解析不可变 intent，并只向隔离子 Agent 暴露预绑定、无参数的工具。

公共生命周期是封闭的：

```text
launch   prepare -> submit
inspect  status -> optional tail
finalize collect -> parse
cancel   cancel
```

不存在公共 `prepare`、`submit`、`status`、`tail`、`collect` 或 `parse` operation；
它们是私有确定性动作。子 Agent 不能修改参数、调用其他工具或选择科学方法。

## 内容

- [发现输入](#发现输入)
- [Launch](#launch)
- [Inspect](#inspect)
- [Finalize](#finalize)
- [Cancel](#cancel)
- [重试与重新计算](#重试与重新计算)
- [结果权威性](#结果权威性)

## 发现输入

读取：

```text
research_read mode=artifacts
research_read mode=capabilities capabilityKind=compute
```

Artifact catalog 提供逻辑 `art_...` ID、路径、SHA-256、所有者和兼容 role。Capability
catalog 提供 capability ID/version、参数形状、输入/输出 role 与解析合同；它不能证明实时
软件或环境处于健康状态。

若新 workspace 没有合适输入，先启动一个未关闭的 ResearchNode。对单个连通 SMILES
使用 `artifact_seed`，对有边界的 Gaussian、XYZ 或 xTB control 文本使用 `artifact_import`。Host
返回逻辑 ID；调用方不得自行创建 `art_*` 值或 workspace 路径。

## Launch

Launch 接受完整语义请求和所选执行目标：

```json
{
  "operation": "launch",
  "nodeId": "node_1",
  "purpose": "Optimize and characterize one TS candidate.",
  "capability": "gaussian.opt_freq",
  "capabilityVersion": "1",
  "attemptKind": "primary",
  "inputArtifacts": [
    {"inputRole": "gjf", "artifactId": "art_..."}
  ],
  "parameters": {"method": "M062X", "basis": "6-31G(d)"},
  "executionTarget": {
    "kind": "remote",
    "environment": "cluster_1w",
    "resources": {
      "queue": "batch", "nodes": 1, "ncpus": 8,
      "memory": "16gb", "walltime": "24:00:00", "ngpus": 0
    }
  }
}
```

子 Agent 启动前，Host 创建并校验新的 `ts-calculation-intent/7`，绑定当前 Node 合同，
解析路径与摘要，分配预期 Artifact，并冻结科学与执行绑定。子 Agent 随后调用 prepare，
且仅在已知 prepare 成功后调用 submit。Submit 只能调用一次；效果未知会结束生命周期并
要求协调确认。

在 Attempt 达到 `parsed`、`failed` 或 `stopped`，且 Root 已记录所需科学解释前，保持
所属 ResearchNode 未关闭。`completed` 只表示调度器/程序已结束，仍需收集和解析；
`collected` 仍需解析。已创建或已准备的 intent 尚未造成外部变更，本身不妨碍放弃 Node。

`launch` 返回提交结果（包括结果不确定）后应结束当前 turn。App Server Monitor 会轮询绑定的 Attempt，在
状态变化时排队 `next_run` 唤醒。等待期间不要调用 `bash sleep`、`wait` 或手动状态循环；
收到 Monitor 唤醒或稍后明确请求后再执行 `inspect`。

执行目标和 `dry_run` 是独立控制项。`executionTarget.kind=local` 时，`dry_run=true`
准备并校验本地计划但不启动程序；`dry_run=false` 在 workspace 的持久化 Attempt 本地
worker 中启动所选 Backend，并支持完整 `submit/status/tail/collect/cancel` 生命周期。
`executionTarget.kind=remote` 时，`dry_run=true` 只准备并校验远端计划；
`dry_run=false` 通过配置的远端环境提交。Host 始终拒绝任意 shell，并将每个命令绑定到
已校验 capability 与不可变 calculation intent。

## Inspect

Inspect 轮询一个已绑定 intent，并可读取一个已声明 Artifact 的尾部：

```json
{
  "operation": "inspect",
  "nodeId": "node_1",
  "intentId": "calc_1",
  "tailArtifact": "gaussian.out",
  "tailLines": 80
}
```

Status 总是先运行。子 Agent 可以立即提交结果，或在诊断有用时调用一次 tail。Tail 仅限
已声明 Artifact basename，最多 500 行。调度器状态、程序状态与输出可用性保持为不同字段。

## Finalize

Finalize 收集允许的输出集，并解析一个已收集 Artifact：

```json
{
  "operation": "finalize",
  "nodeId": "node_1",
  "intentId": "calc_1",
  "artifacts": ["gaussian.out", "program_status.json"],
  "artifactRef": "nodes/node_1/attempts/calc_1/outputs/remote/gaussian.out"
}
```

只有收集完成后才运行 parse。收集过程校验不可变 Artifact manifest；远端收集不依赖调度器
历史。解析器事实属于运行输出。`program_status` 表示可执行程序是否到达正常终点；
`task_validation` 单独表示请求的 capability 是否产生必需输出与收敛证据。因此正常终止的
程序仍可能得到 `task_validation.status=incomplete`。Root 必须核验主要 Artifact，之后才
能通过 `research_change` 记录各项语义 Finding。

## Cancel

Cancel 针对一个已绑定 intent：

```json
{"operation":"cancel","nodeId":"node_1","intentId":"calc_1"}
```

该动作只能调用一次。已知成功具有幂等性。效果不确定的取消必须先协调确认，子 Agent
绝不重放。

## 重试与重新计算

每次 launch 都声明 `attemptKind`。`primary` 禁止 source。只有 capability、输入 Artifact
摘要和参数未改变时，才能用 `attemptKind=retry` 创建新 Attempt。如果这些科学绑定之一
发生变化，但计算仍回答同一个 Node 问题并交付相同主要结果，则使用
`attemptKind=recalculation`。两者都引用同一 Node 中的一个源 Attempt：

```json
{
  "operation": "launch",
  "nodeId": "node_1",
  "attemptKind": "recalculation",
  "sourceAttempt": {
    "intentId": "calc_1",
    "reason": "Check whether the stationary-point conclusion survives the method change."
  },
  "parameters": {"method": "wB97XD", "basis": "def2SVP"}
}
```

Kernel 推导 `changed_fields`，调用方不自行声明 diff。保留源 Attempt。为了回答同一个有
边界问题而改变方法属于 recalculation。独立方法分支、变化的假设、新端点问题或不同主要
交付物需要启动依赖 ResearchNode，并通过 Artifact 绑定消费之前的输出，不能跨 Node 建立
Attempt lineage。

不要混淆新的 retry Attempt 与控制动作重放。类型化的生效前
`retry_same_submission` 结果允许在已有 intent 上重复同一个 submit 动作，不分配新
`calc_*`。新的 `attemptKind=retry` 表示上一个生命周期安全结束后，对未改变科学 intent
进行一次独立执行。

## 结果权威性

模型只填写 `ts_compute_result` 中的 `summary` 与 `limitations`。Host 从类型化 action
journal 推导动作结果、程序状态、Artifact、事实、来源和协调标记。结构化工具返回不能证明
执行成功。程序失败不等于 Claim 被反驳，解析器失败也不等于程序失败。

如果 submit 或 cancel 动作丢失类型化客户端结果，则记录为 `client_result_unknown` 并要求
协调确认。这不能取代 compute Kernel 在提交前上传阶段返回的、更精确的可重试结果。
