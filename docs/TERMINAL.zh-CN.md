# 终端使用说明

[English](TERMINAL.md) | [简体中文](TERMINAL.zh-CN.md)

## 启动

终端和 TS Phone 连接同一个 Host 会话。Host 运行 Pi Worker，并将会话保存在
研究工作区中。

启动已安装的 Phone 服务，然后打开终端：

```bash
systemctl --user start ts-phone-tspi.service
cd /path/to/TSPi-installation
./TSPi
./TSPi --workspace reaction-a
./TSPi --workspace reaction-a --continue
./TSPi --workspace reaction-a --session-id <session-id>
```

安装时配置了 systemd 用户服务即可使用上述服务命令。手动启动使用
`./TSPhoneServer`，详见[Phone 配置](INSTALLATION.md#configure-ts-phone)。

客户端优先选择活动的 Host Controller。可以选择已有会话，使用 `--continue`
打开最近会话，或提供精确会话 ID。打开历史时读取会话；发送消息后创建队列请求，
在工作区可用时开始研究。

## 配置

客户端读取 `.pi/ts-phone/server.env`，已导出的 `TS_PHONE_HOST`、
`TS_PHONE_PORT` 和 `TS_PHONE_STATE_DIR` 优先于文件设置。
`TSPhoneServer` 与 `TSPhoneCtl` 使用同一配置读取器。

终端通过 `127.0.0.1` 或 `::1` 连接，认证时私下读取
`TS_PHONE_STATE_DIR/auth.token`。Pi 模型凭据保存在 Worker 配置的 Pi 目录中。

启动器通过 `PI_BIN` 或 `PATH` 中第一个 `pi` 选择基于 Node 的 Pi 安装，
并从其 SDK 加载终端组件，支持 Pi 0.83 和 0.85 的渲染器导出。
使用独立 Pi 二进制时，需要为共享终端配置基于 Node 的 Pi 安装。

## 操作

Enter 发送消息，Shift+Enter 换行。Ctrl+K 打开命令，Ctrl+O 打开会话。
Page Up/Down 滚动当前页，Ctrl+T 展开工具详情，Escape 关闭选择器。
Ctrl+C、Ctrl+D 和 `/quit` 断开终端，Host Worker 继续运行。

| 命令 | 操作 |
| --- | --- |
| `/projects`、`/sessions` | 浏览项目和会话 |
| `/new` | 在当前项目创建会话 |
| `/continue` | 刷新会话；没有队列能力的 Host 会激活其 Worker |
| `/model` | 选择后续消息使用的模型 |
| `/queue` | 查看请求、取消等待任务，或确认已检查的未知结果 |
| `/abort` | 停止当前显示的生成；取消远端计算使用其相应工具 |
| `/refresh`、`/latest` | 加载最新历史并重新连接 |
| `/start`、`/older`、`/newer` | 浏览历史分页 |
| `/approvals` | 查看并回答当前确认请求 |
| `/receipt` | 检查未确认消息的投递情况 |

启用 `command.queue` 后，多个客户端可以查看和排队请求，Host 在每个工作区
同时执行一个轮次。要在 Host 中继续原生或外部 Pi 会话，先正常退出该进程，再打开
其历史。没有队列能力的 Host 在 Worker 空闲时显式切换。

## 投递与恢复

每条消息携带客户端消息 ID 和会话修订。Host 在通过 Pi RPC 分发前进行校验和去重，
发送被拒绝时保留草稿。

HTTP 回复丢失后，使用 `/receipt` 查询投递。如果回执过期或 Host 运行代次已变化，
先检查历史和 Host 状态，再决定是否重新输入消息。草稿和客户端待定状态保留在当前
终端进程中。

队列请求及其选定模型在确认前持久保存。Host 重启后保留等待请求，将中断的执行标记为
`unknown`，并暂停该工作区后续任务。检查历史和输出、停止未知状态的 Worker 后，
通过 `/queue` 确认结果。模型服务重试耗尽时产生失败回执，生成停止后已完成的工具
操作仍保留记录。

直接投递回执和事件历史是有容量限制的内存记录。重连时，SSE 从检查点继续；游标过旧
时发送当前快照，客户端据此刷新视图。

断开终端、停止生成、关闭 Worker 和取消远端计算分别产生各自的效果。

## 原生 Pi

需要 Pi 原生命令、扩展对话框、组件、Shell 集成或批处理/RPC 参数时，使用
`--standalone`：

```bash
./TSPi --standalone --workspace reaction-a
```

共享终端提供文本输入、Markdown、工具摘要、模型/上下文状态和上述 Host 命令。
`--phone` 选择该共享终端。

## 维护检查

```bash
npm run test:terminal
TS_PHONE_SOURCE=/path/to/ts-phone npm run test:terminal-host
```

集成检查使用临时 Host、模拟 Worker、两个终端 Controller、Phone 请求和真实 PTY，
检查共享 Worker、历史浏览、回执、窗口大小调整和断开。套件验证还包括 Phone 服务、
启动器和会话锁测试。
