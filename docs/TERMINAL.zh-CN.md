# 终端

[English](TERMINAL.md) | [简体中文](TERMINAL.zh-CN.md)

TSPi 终端是连接安装级 Host 的 Pi 原生 TUI。Host 是唯一的会话所有者；终端和
TS Phone 都只是它的客户端，一个 Host 可以服务多个项目。

## 启动 Host

先由 systemd 启动安装级 Host，再连接某个项目的 TUI：

```bash
systemctl --user start ts-app-server-tspi.service
./TSPi --workspace reaction-a
```

使用 `systemctl --user stop|restart|status ts-app-server-tspi.service` 管理 Host 生命周期。

Host 身份位于 `.pi/app-server-host/server-id`；私有 Unix socket
位于 `$XDG_RUNTIME_DIR/tspi/`（也可以通过安装配置指定运行目录）。

## 会话和操作

TUI 使用 Pi 原生 session directory。使用 Pi 标准命令创建、选择、重命名和删除会话。
`--session-id <id>` 连接指定会话，`--continue` 选择最近会话。退出 TUI 只会断开当前
客户端，不会停止 App Server。

Ctrl+C 中断当前本地 turn，`/abort` 向 App Server 请求中止当前 agent run。断线后不会
自动重发 prompt；请先检查历史，再决定是否重试。

## 手机访问

TS Phone 通过 Pi Radius 使用 protocol v8 一次连接 Host，然后列出或创建项目，
并创建或切换会话。
它不连接终端进程，也不需要本地 HTTP 服务、bridge secret、反向代理或
`TSPhoneServer`/`TSPhoneCtl`。

Host 提供 `WorkspaceDirectory.list/create` 用于项目列表和创建；新会话通过
`SessionManagement.create({ workspaceId })` 请求。Host 会把名称解析为经过验证的
直接子工作区，并在 session summary 中记录其 cwd。
TS Phone 客户端也必须声明并使用这两个 service；只支持列表和切换的旧版 Phone
需要更新后才会显示创建操作。

Phone 是可交互的 Pi 客户端，不是只读投影。手机提交的 prompt 在 App Server 所在
机器的目标工作区执行，与同一 session 的终端共享 `read`、`write`、`bash` 和全部
包内工具。传输层不会按 Phone 身份过滤命令；Host 账户、工作区、能力合约和操作系统
权限仍然正常生效。

## 浏览器控制

TS Web 默认直接读取 canonical ResearchMap。如果浏览器需要控制一个已经存在的 Pi 会话，
在 Host 运行时启动可选的 loopback adapter：

```bash
./TSPi --gateway --workspace reaction-a --session-id <session-id> \
  --port 8767 --auth-token '<private-token>'
```

adapter 使用版本化的 `tspi-session-control/1` 请求合约和 SSE transcript 流，
只附着到 Host 会话，不会启动第二个 Worker。Phone 客户端继续直接使用 Pi Radius。

## 故障排查

- `workspace is unavailable`：先完成项目 bootstrap，再确认 Host 服务正在运行。
- `App Server is not running`：启动单一 Host service 或上面的命令。
- `another Root Agent already owns workspace`：复用现有 Host，不要为同一安装启动第二个。
- App Server UUID 变化表示指向了不同安装或工作区，请在手机端有意更新连接配置。

详见[中文架构](ARCHITECTURE.zh-CN.md)和[安装说明](INSTALLATION.zh-CN.md)。
