# 终端

TSPi 终端是连接安装级 Host 的 Pi 原生 TUI。Host 是唯一的会话所有者；终端和
TS Phone 都只是它的客户端，一个 Host 可以服务多个项目。

## 启动 Host

在安装目录运行：

```bash
./TSPi --host
```

保持该进程运行，再在另一个终端连接某个项目的 TUI：

```bash
./TSPi --workspace reaction-a
```

如果安装器启用了 systemd Host service，可启动：

```bash
systemctl --user start ts-app-server-tspi.service
```

Host 身份位于 `.pi/app-server-host/server-id`；私有 Unix socket
位于 `$XDG_RUNTIME_DIR/tspi/`（也可以通过安装配置指定运行目录）。

## 会话和操作

TUI 使用 Pi 原生 session directory。使用 Pi 标准命令创建、选择、重命名和删除会话。
`--session-id <id>` 连接指定会话，`--continue` 选择最近会话。退出 TUI 只会断开当前
客户端，不会停止 App Server。

Ctrl+C 中断当前本地 turn，`/abort` 向 App Server 请求中止当前 agent run。断线后不会
自动重发 prompt；请先检查历史，再决定是否重试。

## 手机访问

TS Phone 通过 Pi Radius 使用 protocol v8 一次连接 Host，然后列出项目并切换会话。
它不连接终端进程，也不需要本地 HTTP 服务、bridge secret、反向代理或
`TSPhoneServer`/`TSPhoneCtl`。

## 浏览器控制

TS Web 默认仍然是只读科学投影。如果浏览器需要控制一个已经存在的 Pi 会话，
在 Host 运行时启动可选的 loopback adapter：

```bash
./TSPi --gateway --workspace reaction-a --session-id <session-id> \
  --port 8767 --auth-token '<private-token>'
```

adapter 使用版本化的 `tspi-session-control/1` 请求合约和 SSE transcript 流，
只附着到 Host 会话，不会启动第二个 Worker。Phone 客户端继续直接使用 Pi Radius。

## 故障排查

- `workspace is unavailable`：先完成项目 bootstrap，再运行 `TSPi --host`。
- `App Server is not running`：启动单一 Host service 或上面的命令。
- `another Root Agent already owns workspace`：复用现有 Host，不要为同一安装启动第二个。
- App Server UUID 变化表示指向了不同安装或工作区，请在手机端有意更新连接配置。

详见[中文架构](ARCHITECTURE.zh-CN.md)和[安装说明](INSTALLATION.md)。
