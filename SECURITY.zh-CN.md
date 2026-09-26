# 安全策略

## 支持版本

安全修复面向 `main` 最新版本和最新发布的 TSPi release。旧版本可能不会继续获得 Host、
Link Relay、Native Pi Harness 或 workspace 格式的安全修复。

## 报告漏洞

不要在公开 issue 中报告可利用漏洞。请使用本仓库的私有 GitHub security advisory，或
通过仓库主页列出的私密渠道联系维护者。

请提供受影响 revision、部署模式、最小复现、影响范围，并删除凭据和 workspace 数据。
不得发送 SMTP 授权码、SSH key、模型 token 或私有研究 Artifact。

维护者会确认收到报告，协调修复或缓解措施，并在用户有可执行的修复路径后发布说明。

## 部署注意事项

`.pi` 状态、`compute.toml`、通知配置和 Host socket 应只允许所有者读取。除非已经配置并
审查 gateway 认证与 origin policy，否则浏览器控制只绑定 loopback。远程计算主机和 Link
Relay 基础设施都应视为可信边界；发生事故后应轮换凭据。
