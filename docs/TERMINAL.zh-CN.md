# 终端

[English](TERMINAL.md) | [简体中文](TERMINAL.zh-CN.md)

`TSPi --workspace <name>` 启动的是 Pi 官方的远程 `ExperimentalClientTui`，不会替换
Pi 的 header、editor、命令目录、transcript、extension 或输入循环。选中的 workspace
绑定到安装级 Pi Harness format-4 会话。

## 运行边界

```text
Pi App Server / SessionWorker  <->  TSPi Host  <->  TS Phone/Web
       AgentHarness、历史、工具          Host RPC       Link/HTTP
                 ^                         ^
             Pi 原生 TUI                 Monitor
```

Pi Harness worker 拥有 agent loop、模型、工具、transcript 和 durable format-4 lane。Host
负责路由、认证、幂等回执、scheduler lease、会话发现以及 Monitor supervisor。Pi 原生
TUI、Phone、Monitor 都是同一个 lane 的客户端，不会启动第二个 agent loop。

## 打开工作区

```bash
./TSPi --workspace reaction-a
./TSPi --workspace reaction-a -c
```

启动器先确保安装级 Host 在线，再请求 session descriptor，直接把 Pi 官方 native client
连接到 Pi App Server socket。Native Pi Harness 是唯一支持的后端，不提供 tmux 或 PTY scraping
路径。同一 workspace 的第二个终端会连接同一个 format-4 session；客户端关闭不会
停止 worker，也不会打断当前 turn。

Host 是安装级服务，会扫描 workspace root 下的直接子工作区。通常使用：

```bash
systemctl --user start ts-app-server-tspi.service
systemctl --user status ts-app-server-tspi.service
```

system service 去掉 `--user`。Host 私有 socket 位于配置的 runtime 目录。

## 会话和操作

远程 `ExperimentalClientTui` 提供 `/resume`、`/model`、`/thinking`、`/compact`、
`/reload` 以及 Native TSPi 命令。`/resume` 只能切换当前 workspace 中的 format-4
session，不会跨 workspace。独立 Pi 的会话命令在这个远程客户端中不可用。

启动时，`-c` 选择当前 workspace 最近的可写 format-4 session，`--session-id <id>` 选择
指定 session。顶层 `-r`/`--resume` 会被明确拒绝，因为 Host-mediated client 必须先取得
确定的连接 descriptor 才能启动 TUI；请先进入终端，再执行 `/resume`。Phone/Web 的
prompt 通过 Host `input/send` 进入同一个 lane，并使用持久回执和稳定的
`client_message_id`。

输入历史会从当前选中的 session 恢复，并且按 session 隔离；切换会话后可用编辑框的上下
方向键查找该会话已经接受的 prompt。

分离、打断和退出不是同一件事：终端 detach 只是客户端断开；`Esc` 或 Host 的
`turn/interrupt` 请求打断当前 turn；`/quit` 才结束 Pi。连接在提交后丢失时 Host 会
报告 `uncertain`，不会悄悄重放 prompt；磁盘上的 `dispatching` 回执在 Pi 到达
`submitted/observed` 边界前也不会报告为 accepted。应先检查会话，再用同一个业务 ID 重试。

## Phone、浏览器与 Monitor

TS Phone 通过 TSPi Link 使用版本化 `tspi-host/1` NDJSON 方法。Relay 只转发不透明
帧，不拥有 session 或 ResearchMap。可选 browser gateway 只附着一个已经存在的会话，
通过 loopback HTTP/SSE 提供 snapshot 和事件，不启动 Pi 或 worker。

Host 为 workspace root 启动一个 Monitor worker。Monitor 轮询持久化 Compute 状态，在
workspace 内写入 event/delivery 回执；wake 与用户通知分别确认，带租约和退避。wake
只是“已接受的输入”，不代表 agent 已完成；Root Agent 仍须重新读取状态并检查计算。
Monitor 不会自动 finalize，也不会修改 ResearchMap。

`workspace.json` 保存类似 `ws_<hex>` 的稳定科学身份，而 Host RPC 使用
`reaction-a` 这样的直接目录名。Monitor 会先验证 canonical identity，再做路由转换，
避免跨项目投递。

## 会话存储

安装级 `.pi/app-server-host/sessions/` 是 Native Pi Harness 使用的唯一 session 存储。
workspace `.pi/sessions/*.jsonl` 历史不是受支持的输入，Native runtime 不会 resume 或导入它。
研究状态应保存在 workspace Research Memory；format-4 session 使用 Host 的会话控制接口。

详见[架构](ARCHITECTURE.zh-CN.md)和[安装说明](INSTALLATION.zh-CN.md)。
