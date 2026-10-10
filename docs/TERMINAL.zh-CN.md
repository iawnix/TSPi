# 终端

[English](TERMINAL.md) | [简体中文](TERMINAL.zh-CN.md)

`coragent --workspace <name>` 是用户侧统一入口，启动 Pi 官方的远程 `ExperimentalClientTui`，不会替换
Pi 的 editor、transcript 渲染或输入循环。它与普通 Pi 的 InteractiveMode 是两套界面，
命令和扩展能力以实验性远程客户端为准。选中的 workspace
绑定到安装级 Pi Harness SQLite durable 会话。

工作区统一使用 research 模式，启动时无需选择模式。创建或继续工作区的命令见下文。

## 运行边界

```text
CoRHub/Web ── Link/HTTP ──┐
Pi 原生 TUI ─ Unix/SSH ─────┼─> CoRAgent Agent Server / Host API
Monitor ─ Host RPC ─────────┘       ├─ Root Agent Session
                                    └─ Harness / Pi App Server / SessionWorker
```

Host 是 Agent Server 的 API 和宿主层，负责路由、认证、非输入 RPC 回执、会话发现
以及 Monitor supervisor；Harness worker 在同一个 Agent Server 内拥有 agent loop、模型、工具、
transcript 和 SQLite durable lane。Pi 原生 TUI、Phone、Monitor 都是同一个 lane 的客户端，
不会启动第二个 agent loop。

Host client 的 RPC transport 可以是本机 Unix socket，也可以通过 SSH 启动远端
`coragent-host-proxy`，把同一份 `coragent-host/2` NDJSON 通过 SSH stdin/stdout 转发到远端私有
socket。SSH transport 只改变连接路径，不改变 workspace、session 或 Agent lane 的拥有者。

连接远端安装时，需要同时提供远端 Host socket 和 proxy 路径：

```bash
./coragent --workspace reaction-a \
  --remote-host pi.example \
  --remote-host-socket /run/user/1000/coragent/host.sock \
  --remote-proxy-path /opt/coragent/apps/agent/transport/ssh.mjs \
  --ssh-config ~/.ssh/config
```

启动器会对 Host 返回的 Pi App Server socket 再使用同一个 SSH proxy，并给 Pi 一个本地私有
Unix endpoint。workspace 和 session 仍由远端 Host 持有；本地目录只用于 presentation cwd。

## 打开工作区

```bash
./coragent --workspace reaction-a
./coragent --workspace reaction-a -c
```

启动器先确保安装级 Host 在线，再请求 session descriptor，直接把 Pi 官方 native client
连接到 Pi App Server socket。Native Pi Harness 是唯一支持的后端，不提供 tmux 或 PTY scraping
路径。同一 workspace 的第二个终端会连接同一个 SQLite durable session；客户端关闭不会
停止 worker，也不会打断当前 turn。

Host 是安装级服务，会扫描 workspace root 下的直接子工作区。通常使用：

```bash
systemctl --user start coragent.service
systemctl --user status coragent.service
```

system service 去掉 `--user`。Host 私有 socket 位于配置的 runtime 目录。

## 会话和操作

远程 `ExperimentalClientTui` 提供 `/resume`、`/model`、`/thinking`、`/compact`、
`/reload` 以及 Native CoRAgent 命令。`/resume` 只能切换当前 workspace 中的 SQLite durable
session，不会跨 workspace。切换会释放当前 TUI 连接，再附着选中的会话；后台任务继续运行。
独立 Pi 的其它会话命令在这个远程客户端中不可用。

CoRAgent 提供以下客户端命令，名称、参数和补全由同一命令目录定义：

- `/research`：由当前 worker 执行只读查询，查看 Memory 上下文和记录，包括 SSH 连接的远端工作区；具体选项以命令帮助为准。长结果在独立阅读页中查看。
- `/sys-prompt`：直接读取当前 worker 的 CoRAgent system prompt manifest 和来源，不调用模型。
- `/resume [session-id]`：在当前工作区选择或指定会话；取消选择保持当前会话。
- `/usage`：在紧凑面板中查看当前会话的 token 总量、上下文和各模型用量。
- `/monitor`：在实时面板中查看当前会话的运行、排队作业、待投递事件和最近检查时间。
- `/quit`：断开当前终端，保留后台 worker 和任务。

无实际诊断功能的 `/debug` 已移除。

命令成功提示在 3 秒后消失，普通说明在 5 秒后消失；错误保留到关闭或下一次提交。
提交新消息会清除已完成的命令提示。选择器或详情页打开时，`Esc` 先返回聊天；
普通聊天中 `Esc` 打断当前 turn，临时命令提示不会拦截该操作。

用量、监控、模型、思考等级、会话选择面板，以及 slash 补全列表，均在 Monitor 行上方展开。
系统提示词和较长的研究结果替换上方阅读区域，标题和返回/滚动提示固定。
所有界面都保留底部 Monitor、输入框和模型/上下文信息；面板打开时保留输入草稿和光标位置，
输入框暂时不可编辑，点击也不会抢走命令焦点。
上下键只滚动内容，不改变面板高度；短文档只显示返回提示。
关闭后恢复输入草稿、光标和聊天阅读位置；面板打开期间隐藏后台任务的取消快捷键提示。

输入框正上方常驻一行简短的 Monitor 状态：
`Monitor ✓` 正常，`Monitor …` 检查中或短暂重连，`Monitor !` 警告，`Monitor ×` 错误。
`· ↻2` 表示当前会话有 2 个正在运行的作业；排队作业在 `/monitor` 中单独统计。
`↻0` 表示没有正在运行的作业，`↻—` 表示暂时无法取得数量。
可选的 `· ↑N` 表示尚未完成投递的监控事件数量，正常待投递不会标黄。
没有运行作业、打开选择器或阅读页时也保持显示。补全列表保留 Pi 原有的键盘和鼠标操作。
终端缩放或多行输入使输入框变高时，Monitor 随输入框移动；打开命令面板不会改变两者的位置关系。
后台刷新不会改变命令选择、阅读位置或输入焦点。`/monitor` 展示任务数量、
警告原因和最后检查时间；任务计数属于当前会话，worker 健康状态由各工作区共享。

启动时，`-c` 选择当前 workspace 最近的可写 SQLite durable session，`--session-id <id>` 选择
指定 session。顶层 `-r`/`--resume` 会被明确拒绝，因为 Host-mediated client 必须先取得
确定的连接 descriptor 才能启动 TUI；请先进入终端，再执行 `/resume`。Phone/Web 的
prompt 通过 Host `input/send` 进入同一个 lane，并使用持久回执和稳定的
`client_message_id`。

输入历史从当前 session 的活动 transcript 恢复，并按 session 隔离；切换会话后可用编辑框的上下
方向键查找已接受的 prompt。重新打开时，压缩之前已不在活动 transcript 中的输入暂不恢复。

分离、打断和退出不是同一件事：终端 detach 只是客户端断开；`Esc` 或 Host 的
`turn/interrupt` 请求打断当前 turn；`/quit` 仅关闭当前终端连接。输入发送后若响应丢失，用相同
`client_message_id` 查询 `input/status`。Pi 持久 submission 负责接收与完成状态；
同一业务 ID 重试不会再产生一条输入。

## Phone、浏览器与 Monitor

Phone 客户端必须通过 CoRAgent Link 使用版本化 `coragent-host/2` NDJSON 方法。Relay 只转发不透明
帧，不拥有 session 或 Research Memory。可选 browser gateway 只附着一个已经存在的会话，
通过 loopback HTTP/SSE 提供 snapshot 和事件，不启动 Pi 或 worker。

Host 握手仅接受 `protocol: "coragent-host/2"`，v1 客户端必须更新。能力列表与调用方法统一用斜杠。
会话读取和附着只接受 `after_cursor: {epoch, sequence}`；Host epoch 改变时返回当前快照，
不重放旧 epoch 的事件。会话创建/恢复及 `model/select` 统一使用 `model: {provider, id}`。
会话列表只返回 `{sessions: [...]}`，不携带旧 backend 或格式标记。

Host 为 workspace root 启动一个 Monitor worker。Monitor 轮询持久化 Compute 状态，在
workspace 内写入 event/delivery 回执；wake 与用户通知分别确认，带租约和退避。wake
只是“已接受的输入”，不代表 agent 已完成；Root Agent 仍须重新读取状态并检查计算。
Monitor 通过 next_run 投递认证执行事件，不发布科学结论或修改 Node 内容。

`workspace_manifest.json` 中的规范 `workspace_id` 同时绑定科学状态与 Host
路由；不存在独立的科学身份或直接目录 alias 映射。

## 会话存储

安装级 `var/state/pi/sessions/` 是 Native Pi Harness 使用的唯一 session 存储。
workspace `.pi/sessions` 历史不是受支持的输入，Native runtime 不会 resume 或导入它；持久历史位于 `var/state/pi/sessions/<workspace-id>/<session-id>/session.sqlite`，旁边的 `meta.json` 保存路由元数据。
研究状态应保存在 workspace Research Memory；SQLite durable session 使用 Host 的会话控制接口。

详见[架构](ARCHITECTURE.zh-CN.md)和[安装说明](INSTALLATION.zh-CN.md)。
