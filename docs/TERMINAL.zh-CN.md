# 终端

[English](TERMINAL.md) | [简体中文](TERMINAL.zh-CN.md)

`ResearchAgent --workspace <name>` 是用户侧统一入口，启动 Pi 官方的远程 `ExperimentalClientTui`，不会替换
Pi 的 header、editor、命令目录、transcript、extension 或输入循环。选中的 workspace
绑定到安装级 Pi Harness SQLite durable 会话。

新工作区可以在入口处显式绑定不可变模式：

```bash
./ResearchAgent --workspace quick-task --mode light
./ResearchAgent --workspace reaction-a --mode research
```

`light` 创建最小工作区；`research` 创建 Research State 状态，并在终端会话启动前完成
Host admission。已有框架工作区省略 `--mode` 时使用 manifest 中记录的模式，工作区创建后
不能在两种模式之间转换。

## 运行边界

```text
TS Phone/Web ── Link/HTTP ──┐
Pi 原生 TUI ─ Unix/SSH ─────┼─> TSPi Agent Server / Host API
Monitor ─ Host RPC ─────────┘       ├─ Root Agent Session
                                    └─ Harness / Pi App Server / SessionWorker
```

Host 是 Agent Server 的 API 和宿主层，负责路由、认证、幂等回执、scheduler lease、会话发现
以及 Monitor supervisor；Harness worker 在同一个 Agent Server 内拥有 agent loop、模型、工具、
transcript 和 SQLite durable lane。Pi 原生 TUI、Phone、Monitor 都是同一个 lane 的客户端，
不会启动第二个 agent loop。

Host client 的 RPC transport 可以是本机 Unix socket，也可以通过 SSH 启动远端
`tspi-host-proxy`，把同一份 `tspi-host/1` NDJSON 通过 SSH stdin/stdout 转发到远端私有
socket。SSH transport 只改变连接路径，不改变 workspace、session 或 Agent lane 的拥有者。

连接远端安装时，需要同时提供远端 Host socket 和 proxy 路径：

```bash
./ResearchAgent --workspace reaction-a \
  --remote-host pi.example \
  --remote-host-socket /run/user/1000/tspi/host.sock \
  --remote-proxy-path /opt/tspi/apps/app-server/tspi-host-proxy.mjs \
  --ssh-config ~/.ssh/config
```

启动器会对 Host 返回的 Pi App Server socket 再使用同一个 SSH proxy，并给 Pi 一个本地私有
Unix endpoint。workspace 和 session 仍由远端 Host 持有；本地目录只用于 presentation cwd。

## 打开工作区

```bash
./ResearchAgent --workspace reaction-a
./ResearchAgent --workspace reaction-a -c
```

启动器先确保安装级 Host 在线，再请求 session descriptor，直接把 Pi 官方 native client
连接到 Pi App Server socket。Native Pi Harness 是唯一支持的后端，不提供 tmux 或 PTY scraping
路径。同一 workspace 的第二个终端会连接同一个 SQLite durable session；客户端关闭不会
停止 worker，也不会打断当前 turn。

Host 是安装级服务，会扫描 workspace root 下的直接子工作区。通常使用：

```bash
systemctl --user start ts-app-server-tspi.service
systemctl --user status ts-app-server-tspi.service
```

system service 去掉 `--user`。Host 私有 socket 位于配置的 runtime 目录。

## 会话和操作

远程 `ExperimentalClientTui` 提供 `/resume`、`/model`、`/thinking`、`/compact`、
`/reload` 以及 Native TSPi 命令。`/resume` 只能切换当前 workspace 中的 SQLite durable
session，不会跨 workspace。独立 Pi 的会话命令在这个远程客户端中不可用。

启动时，`-c` 选择当前 workspace 最近的可写 SQLite durable session，`--session-id <id>` 选择
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

`workspace_manifest.json` 中的规范 `workspace_id` 同时绑定科学状态与 Host
路由；不存在独立的科学身份或直接目录 alias 映射。

## 会话存储

安装级 `.pi/app-server-host/sessions/` 是 Native Pi Harness 使用的唯一 session 存储。
workspace `.pi/sessions` 历史不是受支持的输入，Native runtime 不会 resume 或导入它；持久历史位于 `.pi/app-server-host/sessions/<workspace-id>/<session-id>/session.sqlite`，旁边的 `meta.json` 保存路由元数据。
研究状态应保存在 workspace Research Memory；SQLite durable session 使用 Host 的会话控制接口。

详见[架构](ARCHITECTURE.zh-CN.md)和[安装说明](INSTALLATION.zh-CN.md)。
