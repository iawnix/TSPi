# ADR 0004：统一 App Server Extension Runtime

[English](0004-unified-app-server-extension-runtime.md) | 简体中文

- 状态：已接受；已退役的 ordinary-Pi bridge 不属于运行时
- 日期：2026-09-17

## 决定

安装级 Pi App Server 拥有 Root Agent runtime，客户端附着它的 session。Pi
`SessionWorker`/`AgentHarness` 是 runtime owner；TSPi Host 是路由、回执、Monitor 和
Link control plane。终端使用 Pi 官方 native remote client，Phone 和 Monitor 通过
Host adapter 访问同一个 worker lane。

服务工具由 `extensions/server/extensions.json` 选择，每个 descriptor 绑定 scope、
工具清单、权限和 SHA-256 digest。loader 拒绝 package 外路径、符号链接、未知 allowlist
名称、非法 factory 以及和内建工具或其他 extension 的名称冲突。客户端只能调用由
Host context 创建的 protocol service。

worker 加载经过 digest 校验的 server tool facet，以及 package skills、hooks、策略和
system prompt。presentation facet 只在 client 侧生效，不能改变 worker 拥有的工具集合。

## Provider 兼容性

Compute 和 Review runtime 仍校验结果 tool call。对声明 DeepSeek 风格 thinking mode
的 provider，不发送命名 `tool_choice`，因为该组合会被 provider 以 HTTP 400 拒绝；
普通 provider 继续使用命名 choice。结果 schema 和修复回合仍是权威合同。

## 后果

旧 ordinary-Pi bridge 仅作为历史设计背景保留；它不会被打包、选择或由本运行时访问。
