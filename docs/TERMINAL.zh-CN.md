# 终端

TSPi 终端是连接工作区 App Server 的 Pi 原生 TUI。App Server 是唯一的会话所有者；
终端和 TS Phone 都只是它的客户端。

## 启动工作区

在安装目录运行：

```bash
./TSPi --app-server --workspace reaction-a
```

保持该进程运行，再在另一个终端连接 TUI：

```bash
./TSPi --workspace reaction-a
```

如果安装器启用了 systemd 模板，可启动对应实例：

```bash
systemctl --user start 'ts-app-server-tspi@reaction-a.service'
```

App Server 身份位于 `workspaces/reaction-a/.pi/app-server/server-id`；私有 Unix socket
位于 `$XDG_RUNTIME_DIR/tspi/`（也可以通过安装配置指定运行目录）。

## 会话和操作

TUI 使用 Pi 原生 session directory。使用 Pi 标准命令创建、选择、重命名和删除会话。
`--session-id <id>` 连接指定会话，`--continue` 选择最近会话。退出 TUI 只会断开当前
客户端，不会停止 App Server。

Ctrl+C 中断当前本地 turn，`/abort` 向 App Server 请求中止当前 agent run。断线后不会
自动重发 prompt；请先检查历史，再决定是否重试。

## 手机访问

TS Phone 通过 Pi Radius 使用 protocol v8 连接同一个 App Server。它不连接终端进程，
也不需要本地 HTTP 服务、bridge secret、反向代理或 `TSPhoneServer`/`TSPhoneCtl`。

## 故障排查

- `workspace is unavailable`：先用 `TSPi --app-server --workspace <name>` 创建工作区。
- `App Server is not running`：启动匹配的 systemd 实例或上面的命令。
- `another Root Agent already owns workspace`：复用现有 App Server，不要为同一工作区启动第二个。
- App Server UUID 变化表示指向了不同安装或工作区，请在手机端有意更新连接配置。

详见[中文架构](ARCHITECTURE.zh-CN.md)和[安装说明](INSTALLATION.md)。
