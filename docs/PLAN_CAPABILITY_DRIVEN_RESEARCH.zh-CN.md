# Capability 与计算说明

[English](PLAN_CAPABILITY_DRIVEN_RESEARCH.md) | 简体中文

Capability 是执行描述，不是研究状态。它声明有界输入、输出、版本和确定性的失败
行为。Root Agent 决定何时为 ResearchNode 调用能力；Kernel 不负责路由到下一个 Node。

## 所有权

| 内容 | 所有者 |
| --- | --- |
| phase、claim、node、finding、gate | `ResearchMap` 与 `ResearchKernel` |
| 流程和能力指导 | Skill |
| 软件调用与解析 | Backend |
| 本地/容器/HPC 放置 | Compute `Platform` profile |
| attempt、artifact、scheduler 回执 | workspace 操作记录 |
| 浏览器展示 | 直接读取 `ResearchMap.to_dict()` 的 TS Web |

`FactFinding` 和 `IssueFinding` 是 Node 写入 map 的科学输出。解析结果可以先作为
操作 artifact 保存，Root Agent 核验后再提交 `create_finding`。Gate 评估也是 map 记录，
不会隐式改变 Claim 状态。

## 统一计算

安装目录只维护一份 `.pi/compute.toml`。profile 目录同时包含
`kind = "local"` 和 `kind = "remote"`，两者使用同一套
`prepare -> submit -> inspect -> collect -> parse` 生命周期；remote profile 额外带
SSH 和 scheduler 字段。`/compute list` 与 `/compute show <name>` 查询同一目录，
本地和远端不再使用两套公开词汇。

## 验证

测试应覆盖能力输入边界、源 artifact 重放、digest 绑定和显式 ChangeSet 提升。能力不
能作为副作用修改 Claim、关闭 Node 或选择下一个科学问题。
