---
name: research-memory
description: 用持久问题 Node、显式关系、执行观察与不可变 Result 恢复和推进研究。
---

# Research Memory

先读注入的工作区上下文或 `research_read {}`。上下文在预算内保留原始用户要求、关键 Node、Result 与执行事实；省略不表示不存在或已经完成。按返回引用继续读取。执行回执记录事实，领域 Skill 和 Agent 负责科学解释。

## 五种小操作

- `research_read {}` 恢复概览；`{ref}` 读取返回的 Node、Result 或记录，长内容按返回分页继续读取。
- `research_search {query}` 检索研究内容；只用工具 schema 声明的过滤和分页字段，复制精确引用。
- `research_create {goal}` 创建局部研究问题；title、proposal、plan 和初始关系可选。
- `research_update {node_id, note}` 追加观察或解释；按需修改 proposal、plan、progress、status（open / paused / closed）、显式关系或 assessment_ref。
- `research_result {node_id, conclusion}` 发布不可变产出；可附 observation、limitations、inputs、evidence_refs 和 files。只有明确要替换综合判断时才设置 as_assessment。

身份、请求去重、读取依据和版本由适配层提供，模型不用填写事务字段。遇到读取版本冲突，读当前 Node，合并研究内容后用新调用提交。Job 新事件不会改变 Node 的内容修订号。没有全局 progress 对象，也不需要回合结束 checkpoint。

Node 很大时，单独读取准备修改的字段：

```json
{"ref":"node_returned_by_create","field":"plan"}
```

支持 goal、title、proposal、plan、progress、status、assessment_ref、relations。省略内容按 next_offset 继续读；同一 Node 版本、同一字段内容的全部页面实际收到后，才能构成替换依据。缺失或未确认页面不能授权覆盖未读内容；版本变化时重新读取。适配层负责确认和合并读取回执。

## 同一个问题可以反复尝试

调参数、换初始构型和同目标下的重试留在同一个 Node。独立问题或需要分别推进的竞争分支才创建新 Node。goal 是问题，proposal 是当前假设或思路，plan 是调查方案。准备材料或报告不必强行提出科学假设。

```json
{"goal":"找到连接 A 与 B 的过渡态","proposal":"可能存在协同成键路径"}
```

检查失败计算后使用实际 Node ID：

```json
{"node_id":"node_returned_by_create","note":"构型 X 未收敛，尚不能否定该路径；准备尝试 Y。","plan":"由 Y 搜索，随后检查频率与 IRC 连通性。"}
```

## 必要关系只声明一次

`add_relations` 的每项包含 kind（requires / part_of / alternative_to）、target 及可选 reason。撤回关系用 `remove_relations` 中的返回关系 ID。反向查询和历史由框架维护，无需分别修改两端。

```json
{"node_id":"node_comparison","note":"候选取得可比较的能量与连通性证据后进行比较。","add_relations":[{"kind":"requires","target":"node_candidate","reason":"需要候选的可比较结果"}]}
```

map 可以有反馈和备选路径。requires 表达研究意图，不是工具准入条件。实际材料使用和明确结果引用保留具体版本；读过、搜索过某份结果不等于采用了它。

## 结果可以是否定或证据不足

退出码为零不证明科学结论；新失败不覆盖旧证据。发布 Result 不强制关闭 Node；closed 表示停止主动推进，不表示假设成立。

```json
{"node_id":"node_candidate","conclusion":"该候选的 IRC 未连接目标产物。","evidence_refs":["a7"],"limitations":"仅检查该候选，不能排除其他构型。"}
```

文件使用 `files: [{name, purpose?, artifact_ref}]` 引用已登记材料，不把可修改工作文件当成固定结果。修正旧结果时另发 Result 并明确 supersedes；普通新结果不自动替换综合判断。上游修正只产生复核提示，不自动替换旧输入或重新计算。

Monitor 事件包含 Job 及研究 Node。检查或收集执行后，在这里记录解释；结束回合不需要补齐 disposition。

另见[存储与恢复](references/storage.zh-CN.md)、[公开工具](../research-workflow/references/public_contract.zh-CN.md)、[English](SKILL.md)。

## 对象、检查与修订

用 `subjects` 为不可变 Artifact 或 Result 引用指定角色，例如 `{"target":"a1","calculated":"a2"}`。Node 记录研究目标对象，Result 记录实际解释的对象。角色标签不证明身份正确；领域工具比较结构，Memory 不解析分子或裁定科学真伪。

分开记录 `observation`、`conclusion` 和精确的 `check_refs`。检查失败、无法判断也可以保存和引用。检查回执分别记录执行、解析与有限范围的科学检查。

一起修订当前判断和进度时，使用 `supersedes`、`as_assessment:true` 与 `progress`。这条操作是原子的：读取版本冲突时，两者均不保存；不带 progress 的普通发布继续保持原有的结果保存语义。更换 subjects 前先读取该字段。

读取 Result、当前结论卡片和生成的 Markdown 时，若节点上下文变化或引用结果被替代，会显示需复核提示。报告用带 files 和精确 inputs 的 Result 登记，同样适用。提示不代表结论已被否定，不自动重写历史结果、报告或进度。
