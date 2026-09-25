# Root Agent 变更协议

Root 负责科学判断，Kernel 负责结构有效性与原子存储；两者职责必须分开。

## 变更前

读取足够回答问题的最小 `research.read` 结果：

```text
summary -> map -> detail/locate -> artifacts/capabilities/runs
```

明确问题、当前不确定性、负责该工作的 Node，以及支持拟议变更的来源记录。复用已有 ID。
当问题、交付物或 Claim 范围发生变化时创建新的依赖 Node；重试同一个计算仍是在同一
Node 下新增 Attempt。

## 变更中

提交一个带具体理由和有序 operations 的 `research.change` 请求。用 `create_finding` 记录已核验
的 Node 输出，并选择 `kind=fact` 或 `kind=issue`。Finding 的 statement 应保持单一、
明确，并通过 `source_refs` 引用 Artifact ID 等来源。只有某项标准需要在 map 中可见时才
使用 `create_gate`，然后用当前证据引用调用 `evaluate_gate`。

不要从工具成功返回推断科学结论。先检查主要 Artifact 和执行记录。调度器或解析器失败
属于运行信息；只有其科学影响已经确定时才记录 IssueFinding。

## 变更后

读取返回的 revision，并在需要时读取 `research.summary`。只有完成标准已满足且所附每个
NodeGate 的最新评估均为 `pass` 时，Node 才能以 `completed` 关闭。问题未解决时使用
`inconclusive` 或 `stopped`。显式更新 Claim 状态；Node 状态与 Claim 状态互不隐含。

对于新问题，创建依赖于先前 Node 的后继 Node，并在同一个或后续 ChangeSet 中设置焦点。
保留旧 Node、Finding、Gate、Artifact 和 Attempt 作为历史。

## Research Turn 收尾

每轮结束时，读取有界的 `research.context` 或 `research.liveness`，并明确登记生命周期
disposition：用 `research.continuation` 的 `set_required` 记录具体下一动作；让已提交 Attempt 保持
`waiting_external`；带原因记录 `deferred` 或 `blocked`；或在解释证据后关闭相关 map
scope。解析完成或运行记录完成本身不能关闭科学问题。`decision_needed` 要求 Root Agent
继续并登记 disposition；`required` 是合法的下一轮计划，不能由 Harness 在本轮强制执行。
Harness 的 follow-up 只用于修复缺少 disposition 的边界，不能替 Root 选择方法。
Monitor 的 `next_run` 只是运行时唤醒。

## Review

Review 只提供建议，不能写入 map。只向 Review 提供所需的 Claim 和 Artifact，通过
`review.respond` 回答，再使用普通 map operation 记录 Root 接受、拒绝或附带条件的解释。
