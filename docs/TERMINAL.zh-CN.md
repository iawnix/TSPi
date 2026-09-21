# 终端

[English](TERMINAL.md) | [简体中文](TERMINAL.zh-CN.md)

TSPi 终端使用 Pi 原生 remote client TUI，并连接安装级 Host。Host 是唯一的会话所有者；
终端和 TS Phone 都只是它的客户端，一个 Host 可以服务多个项目。启动器会把 TSPi
presentation facet 交给 Pi 的 presentation 和 slash-command registry，因此命令补全、
选择器、transcript 和忙碌状态都沿用 Pi 的原生输入路径；facet 只贡献布局和 TSPi
命令，不接管输入循环。研究 tools、skills 和 system prompt 由 Host/Worker 在服务器侧
加载，终端通过当前 session 使用它们。

## 打开工作区

直接连接项目。Host 未运行时，TSPi 会通过安装时选择的 systemd service（user 或
system scope）启动唯一的安装级 Host，并在 Unix socket 就绪后连接 TUI：

```bash
./TSPi --workspace reaction-a
./TSPi --workspace reaction-a -c
```

user scope 使用 `systemctl --user stop|restart|status ts-app-server-tspi.service`，
system scope 去掉 `--user`；scope 为 none 时受管 Host 被禁用，需先配置 user 或 system service。

Host 身份位于 `.pi/app-server-host/server-id`；私有 Unix socket
位于 `$XDG_RUNTIME_DIR/tspi/`（也可以通过安装配置指定运行目录）。

## 会话和操作

不带会话选项时创建新会话。`-c` 或 `--continue` 选择当前 workspace 最近的会话；
`--session-id <id>` 连接当前 workspace 中的指定会话。TUI 使用 Pi 原生 session
directory；退出 TUI 只会断开当前客户端，不会停止 App Server。

Ctrl+C 中断当前 turn，`/abort` 向 App Server 请求中止当前 agent run。断线后不会
自动重发 prompt；请先检查历史，再决定是否重试。

`Running turn` 表示 Host 已接受 prompt、Agent Lane 正在运行；它不是第二个模型或第二
个服务。模型 token、tool call 和最终消息通过同一个 session 的复制 transcript 返回。
如果状态长时间不变，应检查 Host 日志和 session 事件，而不是再次启动一个终端 Host。

输入 `/` 使用 Pi 的动态命令目录和参数补全。`/model`、`/thinking`、`/compact` 等
内建命令以及 TSPi 的 `/runs`、`/sys_prompt` 会从同一个 registry 注册；底部状态栏
不是命令列表，不能通过点击或复制状态栏文字执行命令。

## 手机访问

TS Phone 通过 TSPi Link 连接 Host。Phone 和 Host 都只向配置的 TSPi Link Relay 建立
出站 WSS，因此 App Server 不需要暴露公网入站端口。Relay 只授权设备并转发不透明的
App Server 字节，不拥有项目、会话或对话历史。

在 Host 上创建一个有效期五分钟、只能使用一次的配对码：

```bash
./TSPi phone pair
```

在 TS Phone 中输入输出的 TSPi Link Relay URL 和配对码。使用 `./TSPi phone devices` 查看已授权
设备，使用 `./TSPi phone revoke <device-id>` 撤销设备。配对后，Phone 可以列出或创建
项目并创建或切换会话；它不连接终端进程，也不需要每个项目单独部署服务。

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
只附着到 Host 会话，不会启动第二个 Worker。Phone 客户端直接使用 TSPi Link。

## 故障排查

- `workspace is unavailable`：检查 workspace 名称及 workspace root 配置。
- `could not start ts-app-server-tspi.service`：根据 scope 使用 `systemctl --user status` 或 `systemctl status` 检查 service。
- `another Root Agent already owns workspace`：复用现有 Host，不要为同一安装启动第二个。
- `TSPi Link is not configured`：先通过安装器注册 Host，再创建 Phone 配对码。
- Host UUID 变化表示指向了不同安装，请重新配对手机。

详见[中文架构](ARCHITECTURE.zh-CN.md)和[安装说明](INSTALLATION.zh-CN.md)。
