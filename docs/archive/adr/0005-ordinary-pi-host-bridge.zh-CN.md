# ADR 0005：普通 Pi Runtime 与 Host Bridge（已退役）

> Historical archive / 历史归档：本文记录旧设计或一次性验证，不是当前接口合同，也不代表本次重构已通过验收。当前设计见 [Research Memory plan](../../RESEARCH_MEMORY_DESIGN_AND_IMPLEMENTATION_PLAN.zh-CN.md)。

[English](0005-ordinary-pi-host-bridge.md) | 简体中文

- 状态：已退役；仅作为历史设计记录
- 日期：2026-09-21
- 范围：旧版启动器、Pi 终端、Host、Phone、Web、Monitor 与会话历史方案

## 决定

本 ADR 曾记录通过 TSPi Host bridge 运行普通 Pi `InteractiveMode` 的过渡设计。该运行时
及其选择开关已删除。当前代码不支持 `TSPI_HOST_BACKEND`、普通运行时回退、`tmux` 持久化
路径或 format-3 历史导入器。

当前运行时使用 Native Pi Harness 与 `tspi-host/2` 协议。本 ADR 仅用于说明旧设计，不是
当前实现契约。当前架构见[架构说明](../../ARCHITECTURE.zh-CN.md)。

## 后果

- `ResearchAgent` 使用 Native Pi Harness；没有普通 Pi 后端或回退路径。
- 不恢复、导入或转换旧工作区及会话格式；新安装使用全新的工作区和会话。
- 保留旧设计记录仅为说明历史，不代表其中提出的运行时或迁移路径仍然存在。
