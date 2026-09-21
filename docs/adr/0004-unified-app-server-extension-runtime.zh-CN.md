# ADR 0004：统一 App Server Extension Runtime

[English](0004-unified-app-server-extension-runtime.md) | 简体中文

- 状态：已接受
- 日期：2026-09-17

## 决定

安装级 systemd App Server 是生产环境唯一的 Root Agent runtime。终端命令
`TSPi --workspace <name>` 是连接它的 Pi client；TS Phone 和 Web 也附着到其会话，
不会启动第二个 workflow runtime，也不会上传可执行 extension。配置 user 或 system
service 时，Host socket 不存在会由终端启动器启动该 service，并等待同一个安装级 Host；
不会创建第二个前台 Host。scope 为 none 时禁用受管 Host，需先配置 user 或 system service。

服务工具由 `extensions/server/extensions.json` 选择，每个 descriptor 绑定 scope、
工具清单、权限和 SHA-256 digest。loader 拒绝 package 外路径、符号链接、未知 allowlist
名称、非法 factory 以及和内建工具或其他 extension 的名称冲突。客户端只能调用由
Host context 创建的 protocol service。

`tspi-server-tools` 是规范 server tool set，所有连接客户端共享其实现。legacy Pi presentation
extension 仅为直接 `pi` 兼容性保留；TSPi workspace 客户端使用 Pi 自己的 remote client TUI，
不会由 TSPi 自动替换其布局。新的 workflow 功能必须增加 server entry 并复用
shared command surface，不得重新创建 per-client broker。

## Provider 兼容性

Compute 和 Review runtime 仍校验结果 tool call。对声明 DeepSeek 风格 thinking mode
的 provider，不发送命名 `tool_choice`，因为该组合会被 provider 以 HTTP 400 拒绝；
普通 provider 继续使用命名 choice。结果 schema 和修复回合仍是权威合同。

## 后果

TUI、Phone 和 Web 共享一份 session transcript 与 Root lock；客户端断开后可由另一个
认证客户端接替，不需要重放不确定 prompt 或远程操作。发布验证必须覆盖 loader、manifest
和 server entry。
