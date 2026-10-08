# Root Agent 单一运行时与原子事务落地计划

> 历史设计记录：其中保留旧 facade、agent-pi-adapter 和 research_compute 的过渡安排，已由 [ADR 0010](adr/0010-retire-parallel-runtimes.zh-CN.md) 的最终清理取代。当前实现以架构文档为准。


## 目标

TSPi 只拥有一个逻辑上的 Root Agent。Terminal、Phone、Web、Monitor 和 SSH 都是接入方式；
Host 是 Agent Server 的 API 和宿主层，属于 Agent Runtime 的一部分。Pi App Server 是 Harness
使用的 runtime implementation，Link Host、Browser Gateway 和 SSH proxy 才是外部连接适配器。
同一个 `workspace_id/session_id` 永远只绑定一个 `SessionWorker` lane，所有客户端看到同一份
会话、研究状态、作业和事件。

本计划只保留一条生产路径：

```text
Terminal ─ Unix socket / SSH ─┐
Phone ─ WSS Relay ────────────┼─> TSPi Agent Server (Host/API)
Web ─ Browser Gateway ───────┤       ├─ Root Agent Session
Monitor ─ Host RPC ──────────┘       ├─ Harness ─ Pi runtime / SessionWorker
                                     └─ Transaction Coordinator
                                                              ├─ Research State
                                                              ├─ Execution Registry
                                                              ├─ Evidence Registry / Payloads
                                                              ├─ Research Memory projection
                                                              └─ Event journal
```

物理上 Pi runtime 可以是 Agent Server 管理的子进程，但它只实现同一个 Root Agent 的 Harness
执行路径；不能再出现第二个独立的 Agent loop、第二套 Research State 或第二套 Artifact registry。

三者关系固定为：

```text
Client API  ──>  Host / Agent Server  ──>  Root Agent Session  ──>  Harness  ──>  tools/model
                  API、路由、事务             决策循环                 执行策略
```

Host 不是 Root Agent 的对立面，也不是另一个 Agent。它是把 Root Agent 变成可连接、可恢复、
可并发订阅服务的宿主；Harness 则是 Root Agent 使用工具、状态和模型的内部运行合同。

## Pi SDK 在其中的位置

TSPi 确实使用 Pi SDK，但当前形态不是调用系统里的 `pi` 命令，也不是把 Agent loop 重新
实现一遍。安装包通过 `config/pi-source.json` 固定 Pi 源码仓库、tag、commit 和 protocol
version，并把 checkout 放在安装目录的 `.pi/runtime-cache/pi/<commit>`。

```text
固定 Pi SDK source
  └─ packages/coding-agent/src/experimental/server.ts
       └─ startForegroundServer()
            └─ Pi SessionManagement / AgentController / Durable Harness
                 └─ PI_SESSION_WORKER_ENTRY = apps/app-server/pi-session-worker.mjs
                      └─ TSPi tools、skills、policy、Research State、Execution、Evidence
```

当前代码的关键适配点是：

* `apps/app-server/tspi-harness-backend.mjs` 动态加载固定版本 Pi 的 server/client runtime，
  创建 Pi server，附着 durable session，并把 AgentController 暴露给 Host；
* `apps/app-server/pi-session-worker.mjs` 使用 Pi 的 `runSessionWorkerWithHarness`，注册
  TSPi 工具、Skill、system prompt、生命周期 hook 和 workspace policy；
* `packages/agent-pi-adapter/pi_runtime_module.mjs` 提供稳定的 `PiSessionPort`，隔离 Pi
  experimental API 的版本变化；
* `apps/app-server/tspi-host.mjs` 负责对外 API、session 路由、回执和事件，把请求送入同一个
  Pi AgentController lane。

因此 Pi SDK 是 Agent 的内核，TSPi Harness 是产品适配层，Host 是 Agent Server 的 API 宿主。
后续事务改造应继续沿用 Pi 的 loop、Harness、Session 和 transcript，只把事务协调器接入
TSPi tool/port 边界；不应再创建第二套 agent loop。

## 事务的定义

事务的原子边界是 workspace 的持久事实和操作回执。一次 Root Agent turn 可以调用多个工具，
但每个持久写入都进入同一个 `TransactionCoordinator`，由它统一获得 workspace 锁、检查基线
revision、写入暂存区并提交。客户端断线只影响响应，不影响已经提交的事务。

计算进程、SSH 命令、网络 provider 等外部副作用无法被文件系统回滚，因此采用两阶段语义：

1. `prepare` 把不可变 intent、Attempt、输入 digest 和待执行命令写入事务暂存区。
2. `commit` 原子提交 workspace 事实，状态为 `submitted`/`pending`。
3. Dispatcher 执行外部副作用，并使用同一个 `job_id/attempt_id` 回写状态。
4. 进程崩溃或网络不确定时进入 `unknown`，由 reconcile 观察、收集或取消；绝不重新解释为
   成功，也不由 Host 猜测科学结论。

因此“原子”保证的是一次提交不会出现半个 ResearchMap、半个 receipt 或过期 projection；
长时间运行的外部作业使用可恢复的操作事务，而不是假装可以回滚已经启动的进程。

这里不把整轮 turn 做成一个跨模型调用、Shell 进程和远程调度器的超大事务。一个 turn 是
带有同一 `turn_id` 的事务链：ChangeSet、作业提交、Artifact 登记和 checkpoint 各自是一个
可恢复的原子提交。这样既保证每个 durable fact 一致，又不会因为模型等待或远程作业运行
数小时而长期占用 workspace 锁。

## 单一事务流程

```text
Client/Root Agent
      │  tx_id + request_id + base_revision + intent
      ▼
Host / Agent Server admission
      │  workspace/session/auth/lifecycle/idempotency
      ▼
TransactionCoordinator.begin
      │  acquire .ts-workspace.lock
      │  load canonical snapshot and verify base_revision
      ▼
prepare
      │  validate ChangeSet / intent / paths / capabilities
      │  stage state, receipt, attempt, artifact manifest and event
      ▼
commit
      │  fsync staged files → deterministic rename → fsync directories
      │  advance one revision and write commit record
      ▼
publish
      │  rebuild memory/context projection, append event, notify subscribers
      ▼
return committed receipt
```

提交失败时只允许两种结果：提交前 `aborted`，或提交后可查询的 `committed`。如果进程在
提交点附近退出，重启时扫描 `operations/transactions/`：有完整 commit marker 的事务重放
publish；只有 prepare marker 的事务清理暂存区并标记 `aborted`。不会靠重试请求重新执行副作用。

## 事务信封

所有内部 port 和 Host RPC 使用同一份信封；transport 不改变字段：

```json
{
  "protocol": "tspi_transaction/1",
  "tx_id": "tx_<uuid>",
  "request_id": "req_<client-idempotency-key>",
  "workspace_id": "ws_<id>",
  "session_id": "ses_<id>",
  "turn_id": "turn_<id>",
  "base_revision": 12,
  "operation": "research.change",
  "intent": {},
  "actor": {"kind": "root_agent", "id": "agent_<id>"},
  "state": "prepared|committed|aborted|uncertain",
  "result_revision": 13,
  "digest": "sha256:<canonical-json>"
}
```

`request_id` 重复且 digest 相同返回原 receipt；重复但 digest 不同返回
`request_id_reused`。`base_revision` 不匹配返回 `revision_conflict`，由 Root Agent 重新读取
bounded context 后再决定，Host 不自动合并科学状态。

## 资源和权威性

| 资源 | 唯一写入者 | 事务内内容 |
| --- | --- | --- |
| `research_map/context.json` | ResearchStateStore | Claim、Node、Finding、Gate、lifecycle 和 revision |
| `lifecycle/liveness.json` | ResearchStateStore | 当前 disposition、checkpoint 和可继续性 |
| `checkpoints/` | ResearchStateStore | turn checkpoint 和事务 revision |
| `nodes/*/attempts/`、`execution/` | ExecutionRegistry | Attempt、Job intent、状态和 reconcile 信息 |
| `evidence/`、`artifacts/<artifact_id>/payload` | EvidenceRegistry/PayloadStore | Artifact manifest、digest、lineage、payload |
| `memory/index.json` | ContextProjection | 从已提交 State 重建的有界 projection |
| `operations/transactions/`、`operations/events/` | TransactionCoordinator | commit journal、receipt、事件顺序 |
| Pi session directory | Root Agent Runtime | transcript、lane、模型状态和临时 session memory |

`ResearchMap` 是研究事实权威；`ResearchMemory` 只是 projection。manifest 中的
`memory_scope=session` 继续表示会话对话记忆范围，`memory/index.json` 改名为
`research_context_projection` 语义并标记 `authority=research_state_projection`，消除“第二个
memory 事实源”的歧义。

## 模块边界和 API

### 1. Agent Server Host（Agent 的 API/宿主层）

文件：`apps/app-server/tspi-host.mjs`、`tspi-host-client.mjs`、
`tspi-host-proxy.mjs`、`tspi-terminal-client.mjs`、`tspi-link-host.mjs`、
`tspi-browser-gateway.mjs`。

Host 负责认证、workspace/session 路由、创建和恢复 Root Agent Session、调用 Harness、admission、
幂等、锁、事务调用和事件订阅。它不执行科学判断，但它与 Root Agent、Harness 共同组成
Agent Server；不应再把 Host 当成 Agent 外部的独立控制平面。

```text
host.initialize() -> protocol/release/capabilities
workspace.list() -> workspaces
workspace.create(request_id, workspace_id) -> workspace
workspace.attach(workspace_id) -> manifest + revision
session.create(request_id, workspace_id) -> session
session.attach(workspace_id, session_id, cursor) -> snapshot + events
turn.submit(request_id, workspace_id, session_id, input) -> turn receipt
turn.interrupt(request_id, workspace_id, session_id) -> interrupt receipt
event.subscribe(workspace_id, session_id, cursor) -> ordered events
transaction.get(workspace_id, tx_id) -> transaction receipt
```

HTTP、Unix socket、SSH proxy、WSS Relay 都只编码/转发上述 Host RPC。`server.mjs` 保留为
HTTP adapter；`app_server.mjs` 不再作为并行生产入口，只保留内部 AgentService Facade。

### 2. Root Agent Session 与 Harness

文件：`apps/app-server/pi-app-server.mjs`、`tspi-harness-backend.mjs`、
`pi-session-worker.mjs`、`pi-session-control.mjs`。

Root Agent Session 负责 prompt loop、决策、transcript 和 session lane；Harness 负责把模型工具
调用接到事务、Research State、Execution 和 Evidence port。Root Agent 通过四个内部 port 访问
宿主能力：

```text
context.read(focus) -> bounded ContextPack
research.change(change_set, base_revision, request_id) -> committed state receipt
execution.start(intent, base_revision, request_id) -> submitted Attempt/Job receipt
evidence.register(payload_ref, request_id) -> Artifact manifest receipt
research.checkpoint(disposition, request_id) -> checkpoint receipt
```

工具不能直接写 JSON、启动任意 Host 子服务或指定另一个 workspace。`pi-native-tools.mjs`
只负责把工具参数翻译成这些 port 调用。`pi-app-server.mjs` 和 `pi-session-worker.mjs` 是
Harness 的当前 Pi 实现细节，不对客户端形成第二个 API。

### 3. TransactionCoordinator

新增：`packages/agent-runtime/transactions/`（JS facade）和
`packages/research-state/research_state/transactions.py`（Python canonical writer）。

```text
begin(envelope) -> tx handle
prepare(tx, participants) -> prepared receipt
commit(tx) -> committed receipt + revision
abort(tx, reason) -> aborted receipt
recover(workspace_root) -> recovery report
reconcile(tx_id) -> committed|aborted|uncertain
```

Coordinator 是唯一允许同时触碰 State、Execution、Evidence 和 projection 的入口。参加者只
实现纯校验和 stage/apply/finalize：

```text
StateParticipant.stage(change_set)
ExecutionParticipant.stage(intent)
EvidenceParticipant.stage(manifest/payload)
ProjectionParticipant.stage(state_snapshot)
```

Participant 不得自行获取第二把锁、修改 revision 或发布事件。

### 4. ResearchStateStore

重用 `packages/research-state/research_state/agent_workspace.py` 的 schema 和 ChangeSet
校验，收敛 `_workspace_lock`、admission、checkpoint、apply_change 为 Coordinator participant。

```text
read_snapshot(workspace_id) -> context + liveness + revision
validate_change(base_revision, change_set) -> prepared state
apply_change(tx_id, prepared_state) -> state files staged
checkpoint(tx_id, disposition) -> checkpoint staged
```

一次 commit 同时更新 `context.json`、`liveness.json`、checkpoint、manifest revision；使用
临时文件、`fsync`、`rename`，并按固定顺序提交，避免当前 admission 中多个文件逐个写入造成
半提交窗口。

### 5. ExecutionRegistry

重用 `packages/job-runtime/` 的 local/remote platform；删除生产路径中的
`apps/app-server/job-artifact-runtime.mjs` 临时 job 实现。

```text
probe(intent) -> readiness
prepare(intent) -> Attempt + JobSpec staged
submit(tx_id) -> submitted receipt
status(job_id) -> current status
collect(job_id) -> output manifests
cancel(job_id) -> terminal status
reconcile(job_id) -> running|succeeded|failed|unknown
```

`job_id` 由 Coordinator 在 prepare 阶段确定并持久化；Local/SSH/Slurm adapter 只执行它，不
生成第二个 id。执行状态改变仍然通过一个新的 Coordinator transaction 写回。

### 6. EvidenceRegistry / PayloadStore

合并 `research_state.evidence`、`research_compute.workspace.artifacts` 和 Node runtime 的
重复 artifact 逻辑。沿用 manifest 中已经声明的 `artifacts/` 目录，统一 payload 路径为
`artifacts/<artifact_id>/payload`，不再新增第二个 `payloads/` 根目录。

```text
register_file(path, expected_digest) -> artifact manifest
create_bytes(bytes, media_type) -> artifact manifest
derive(input_ids, operation, parameters) -> derived manifest
read(artifact_id, offset, limit) -> bytes/excerpt
link(artifact_id, subject_id, relation) -> evidence link
```

artifact ID 根据内容 digest 生成；同一 digest 重放只返回同一 manifest。Artifact 不是
Finding，`link` 只登记证据关系，Finding 仍需 Root Agent 通过 Research ChangeSet 提交。

### 7. ContextProjection 和 EventJournal

`packages/research-memory/research_memory/service.py` 只从 commit 后的 State snapshot 构建
bounded ContextPack，不再作为写入事实源。

```text
project(revision, state_snapshot) -> projection receipt
build_context(focus, limits) -> ContextPack(context_id, source_revision)
append_event(committed_receipt) -> monotonic event
replay(cursor) -> ordered events
```

projection 失败不回滚已提交科学事实；事务 receipt 标记 `projection_pending`，Host recovery
优先重建 projection 后再发送事件。

## Turn 级别规则

Root Agent 的一轮保持现有生命周期，但每个持久步骤走同一 Coordinator：

```text
TRIGGER
  -> ORIENT: read_snapshot/build_context
  -> PLAN: 只产生内存中的 intent
  -> PREPARE: validate + stage
  -> EXECUTE: commit intent / run external job
  -> WAIT/RECONCILE: observe job state
  -> INTERPRET: Root Agent 读取 artifact/evidence
  -> ADVANCE: research.change
  -> CHECKPOINT: research.checkpoint(disposition)
```

一轮的完成条件是 checkpoint receipt 已提交；断线时通过 `turn_id` 查询即可恢复。Host 不
替 Root Agent 选择下一步、不从 job exit code 自动创建 Finding、不把 `next_run` 当成新的
研究指令。

## 现有代码到目标架构的映射

先保留 Pi SDK 和已有 workspace schema，把重复的应用边界收掉：

| 现有位置 | 目标角色 | 修改方式 |
| --- | --- | --- |
| `apps/app-server/pi-app-server.mjs` | Agent Server 进程入口 | 保留为唯一生产启动入口，同时启动 Host API、Pi Harness 和 Worker supervisor |
| `apps/app-server/tspi-host.mjs` | Agent Server Host/API | 保留文件名，改成 Host facade；直接组合 transaction、session、workspace 和 event services |
| `apps/app-server/tspi-harness-backend.mjs` | Harness adapter | 只负责 Pi `AgentController`/`SessionManagement` 适配，不承担 Host RPC 或 Research State 写入 |
| `apps/app-server/pi-session-worker.mjs` | Pi Harness worker | 保留 Pi loop；工具通过 ports 调用事务、State、Execution、Evidence |
| `packages/agent-pi-adapter/` | Pi SDK adapter | 保留；只隔离 Pi experimental API 版本变化 |
| `apps/app-server/server.mjs` | HTTP transport adapter | 删除独立 composition/startup 逻辑，只把 HTTP 请求转发到同一个 Host facade |
| `apps/app-server/app_server.mjs`、`composition_root.mjs` | 旧的第二应用边界 | 不再作为生产入口；迁移需要的 facade 后删除重复 session store 和 runtime 组装 |
| `apps/app-server/tspi-host-client.mjs`、`tspi-host-proxy.mjs`、`tspi-link-host.mjs`、`tspi-browser-gateway.mjs` | 客户端 transport | 保留，只做编码、转发、订阅，不创建 Agent 或 Worker |
| `apps/app-server/job-artifact-runtime.mjs` | 旧临时 runtime | 删除，改由 ExecutionRegistry、EvidenceRegistry 和 PayloadStore 组合 |
| `apps/agent-cli/research_agent_launcher.py` | CLI launcher | 不再启动另一套 HTTP App Server，改为连接唯一 Agent Server 入口 |

目标进程关系如下：

```text
pi-app-server.mjs
  ├─ Host API（tspi-host.mjs）
  ├─ Root Agent session registry
  ├─ TransactionCoordinator
  ├─ Pi Harness backend（tspi-harness-backend.mjs）
  │    └─ Pi SDK AgentController / SessionWorker
  └─ Monitor / Link supervisor
```

客户端看到的仍然只有一个 `Agent Server`。`server.mjs`、SSH proxy、WSS Link 和 browser
gateway 都不能再启动自己的 session store、model loop 或事务写入器。

## 现有代码修改清单

### 第一阶段：先建立唯一边界

1. 新增 `TransactionCoordinator`、transaction envelope schema、receipt schema 和 recovery
   scanner。
2. 将 `tspi-host.mjs` 的 `deduplicate` 改为 Coordinator 的 request journal wrapper；保留
   当前 `stateRoot/requests` 数据，但迁移到 `operations/transactions`。
3. 将 `research_state.agent_workspace` 的 `_workspace_lock` 和各类 `_atomic_json` 收敛为
   participant API；admission、apply_change、checkpoint 只能由 Coordinator 调用。
4. 为每个 commit 写 `operations/transactions/<tx_id>.json` 和
   `operations/events/<revision>.json`，启动时执行 recover。

### 第二阶段：统一作业和 Artifact

1. 删除 `apps/app-server/job-artifact-runtime.mjs` 的 job/artifact 双实现和随机 artifact ID。
2. `pi-native-tools.mjs` 的 job 工具改调用 `ExecutionRegistry`，artifact 工具改调用
   `EvidenceRegistry`。
3. `research_compute/workspace/artifacts.py` 改为只读取 EvidenceRegistry manifest；
   `packages/artifact-store` 的 `PayloadStore` 要么成为该唯一实现，要么删除，不能保留未调用的
   第二实现。
4. 统一路径到现有的 `nodes/.../attempts`、`evidence/`、`artifacts/<artifact_id>/payload`、
   `operations/`，移除 `.tspi/jobs` 和 `.tspi/artifacts`；不增加新的 workspace 根目录。

### 第三阶段：简化 App Server 入口

1. `tspi-host.mjs` 成为唯一 Agent Server 生产入口；它同时拥有 Host API、Root Agent Session
   和 Harness 生命周期；`pi-app-server.mjs` 只是 Harness 的 Pi runtime 实现。
2. `composition_root.mjs` 只组装 Workspace、Session、Transaction、State、Execution、
   Evidence、Context 和 Event ports。
3. `app_server.mjs` 改名义为内部 `AgentService` facade；`server.mjs`、`client.mjs` 仅为
   HTTP adapter/client，不再维护另一套 session store 或 commit 逻辑。
4. `tspi-link-host`、`tspi-browser-gateway`、`tspi-terminal-client` 只做 transport 和
   subscription 映射；禁止创建 SessionWorker。

### 第四阶段：硬切换和清理

1. 删除旧 transaction/ResearchMap/Artifact schema、旧 `.tspi` 路径和兼容 fallback；启动时
   发现旧布局直接报 `legacy_workspace_layout`。
2. manifest、context、liveness、memory projection 的 revision 必须相等；修正当前
   `memory_scope=session` 与 `memory/index.json scope=workspace` 的命名冲突。
3. 所有 public API、`.d.mts`、contract schema、安装器 inventory、文档和测试改为
   `tspi-host/1` + `tspi-transaction/1`。

## API 错误和恢复

固定错误码：

```text
not_initialized
workspace_not_found
workspace_admission_required
revision_conflict
request_id_reused
transaction_not_found
transaction_uncertain
validation_failed
external_effect_unknown
projection_pending
```

客户端只需要三种处理：

* `revision_conflict`：重新读取 context，交由 Root Agent 决策；
* `transaction_uncertain`/`external_effect_unknown`：调用 `transaction.get` 或
  `job.reconcile`，禁止盲目重试；
* 其它明确失败：相同 request_id 可安全重试，成功后返回同一 receipt。

## 分阶段实施和验收

### P0：合同冻结

完成事务 envelope、文件布局、revision 规则、错误码和架构图；新增 schema contract tests。

### P1：Research State 原子提交

实现 Coordinator + State participant；覆盖并发 ChangeSet、revision 冲突、SIGTERM 中断、
重启 recover、重复 request_id 和 projection 重建。

### P2：Root Agent 接入

让 `pi-native-tools` 全部经 port 调用；端到端验证一个 turn 的 change + checkpoint 只产生
一个可查询的 transaction chain。

### P3：Execution/Evidence 接入

验证 `prepare -> commit -> submit -> collect -> register -> link`；人为杀掉 Host 后，
reconcile 必须得到 `unknown` 或真实 terminal 状态，不能重复启动作业。

### P4：多连接验证

用同一个 session 同时连接 Terminal、SSH、Phone/Relay、Web 和 Monitor：所有连接收到相同
的 `epoch/sequence/revision`，只存在一个 SessionWorker。测试服务统一放在
`/home/iaw/debug/tspi-test-env`，测试结束停止并删除 Host、Relay、Node 和 SSH 服务。

最终验收命令序列：

```text
workspace.create
→ workspace.attach
→ session.create
→ turn.submit
→ research.change
→ job.prepare/commit
→ job.reconcile
→ artifact.register
→ evidence.link
→ research.checkpoint
→ transaction.get / event.replay
```

这条路径完成后，系统可以用一句话描述：**一个 Agent Server 宿主一个 Root Agent，多个连接适配器，
一个 Harness，一个事务协调器，一份 workspace 权威状态。**
