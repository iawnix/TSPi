# 公开工具与 checkpoint 契约

由 scripts/update_public_contract.mjs 从公开工具注册表与 Research State 契约生成，不单独编辑。

工具参数以运行时注册的 schema 为准，引用使用工具返回的真实 ID。

```text
system_prompt
research_read
research_change
research_strategy
research_interpretation
research_checkpoint
job_start
job_status
job_collect
job_cancel
job_probe
job_reconcile
artifact_register
artifact_create
artifact_read
artifact_derive
artifact_link
```

Checkpoint disposition：

```text
continue_required
waiting_external
deferred
blocked
terminal
user_input_required
```

Research State 计算 eligible_node_ids、ready_node_ids、blocked_node_ids、running_attempt_ids、needs_checkpoint 与持久接续准入。Host 使用 State 的 tool_admission，Monitor 使用 State 的 wake 准入；Skill 不另行维护这些规则。
