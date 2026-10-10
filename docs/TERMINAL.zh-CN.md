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

Host 是 Agent Server 的 API 和宿主层，负责路由、认证、会话管理 RPC 回执、会话发现
以及 Monitor supervisor；Harness worker 在同一个 Agent Server 内拥有 agent loop、模型、工具、
transcript、用户任务控制回执和 SQLite durable lane。Pi 原生 TUI、Phone、Monitor 都是同一个 lane 的客户端，
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
- `/monitor`：在实时面板中查看当前用户任务、交付条件、等待对象、计算作业和执行记录；完整命令见下文。
- `/quit`：断开当前终端，保留后台 worker 和任务。

无实际诊断功能的 `/debug` 已移除。

Slash 补全在输入框上方使用稳定的候选窗口。上下键选择候选，Tab 或点击只补全，
Enter 打开命令入口；参数候选的 Enter 只补全，再次 Enter 才提交完整命令。
Esc 关闭候选并保留输入，Tab 可重新打开。`/monitor` 按当前参数位置展示子命令和选项，
不会把任务 ID 改成小写，也不会将占位符作为真实参数提交。缺少参数时不执行操作。

命令失败后，如果输入框尚未被编辑，原命令会恢复以便修正；迟到的失败回执不会覆盖新草稿。
错误行保留 `F2 Details` 入口，可查看完整错误与用法，Esc 返回后保留草稿。
路径和以 slash 开头的多行文本按普通消息处理；粘贴本身不会执行命令。

命令面板、选择器和详情页跟随当前 Pi 主题，选中背景与正文颜色来自主题。
`›` 表示键盘焦点，`[current]` 表示已经生效的选项。选择器支持点击和滚轮。
正常运行或排队使用活动色，阻塞使用警告色，执行失败使用错误色，取消使用次级文字色。
`NO_COLOR` 或 `TERM=dumb` 下，命令面板、补全、状态栏及工具摘要保留文字与符号提示。

命令成功提示在 3 秒后消失，普通说明在 5 秒后消失；错误保留到关闭或下一次提交。
提交新消息会清除已完成的命令提示。选择器或详情页打开时，`Esc` 先返回聊天；
普通聊天中 `Esc` 打断当前 turn，临时命令提示不会拦截该操作。

用量、监控、模型、思考等级、会话选择面板，以及 slash 补全列表，均在 Monitor 行上方展开。
系统提示词和较长的研究结果替换上方阅读区域，标题和返回/滚动提示固定。
所有界面都保留底部 Monitor、输入框和模型/上下文信息；面板打开时保留输入草稿和光标位置，
输入框暂时不可编辑，点击也不会抢走命令焦点。
上下键只滚动内容，不改变面板高度；短文档只显示返回提示。
关闭后恢复输入草稿、光标和聊天阅读位置；面板打开期间隐藏后台任务的取消快捷键提示。

输入框正上方的 Monitor 常驻行先显示用户任务，再显示作业数。例如
`Monitor ✓ · Researching · 2 jobs running` 表示正在研究且有两个计算作业运行。
状态分别表达等待计算、准备继续、已暂停、需要处理和已完成；一轮模型回复结束不代表用户任务完成。
断线和快照陈旧优先于缓存中的进展显示；未知数量使用 `—`，不推算完成百分比或时间。
没有运行作业、打开选择器或阅读页时也保持显示。后台刷新保留焦点、选择、阅读位置和输入草稿。

`/monitor` 概览实时展示原始目标、交付条件、最近登记的进展、具体 Job 等待条件、控制原因和
自动推进设置。作业执行与输出收集分别显示；当前科学分析字段标明“Not recorded”，
等待后续有证据的研究投影，不根据 Job 成功推断分析已完成。
Pi generation/tool Task 仅出现在执行详情中，不混入用户任务列表。

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

Monitor 统一用户任务控制与计算作业观察。Task Controller 在 Pi SessionWorker 中运行，
沿用 Harness 的 durable 事务与输入接纳边界；安装级 Monitor worker 观察 Compute 状态并登记执行事件。
模型/工具循环始终由 Pi 持有，科学证据与结论仍归 Research Memory。

| 命令 | 行为 |
| --- | --- |
| `/monitor` | 当前会话的实时概览 |
| `/monitor tasks` | 当前与历史用户任务 |
| `/monitor task <id>` | 目标、交付条件、研究问题、进展及等待条件 |
| `/monitor task pause <id>` | 暂停自动推进，当前工作可以收尾 |
| `/monitor task resume <id>` | 恢复指定用户任务 |
| `/monitor task cancel <id> --keep-jobs` | 取消用户任务，保留其计算作业 |
| `/monitor task cancel <id> --cancel-jobs` | 取消用户任务，并请求取消其计算作业 |
| `/monitor jobs [--task <id>]` | 会话内作业或指定用户任务的作业 |
| `/monitor job <id>` | 作业执行与收集状态 |
| `/monitor job cancel <id>` | 请求取消一个计算作业 |
| `/monitor runs [--task <id>]` | 按 Pi submission/run 分组的执行记录 |
| `/monitor run <id>` | 有界读取 generation/tool 执行详情 |
| `/monitor health` | Task Controller 与共享 Monitor worker 健康信息 |

任务详情展示研究入口、当前关注问题、局部方案摘录、问题原始状态、assessment/Result
引用和相关 Job。只有当前会话归属的 Job 提供 `/monitor job` 命令；其它 Job 保持可见，
并标注 `Outside this session`（不属于当前会话）。共享问题只展示一次，关系通过 ID 引用同一问题。`closed` 显示为
`Ended`（已结束），不表示科学验证成功或用户任务完成。快照省略的内容会明确标注，
可用 `/research read <id>` 继续读取原记录；节点数量不代表研究完成比例。查看不会
修改任务焦点或唤醒模型，也没有单独的规划命令。

列表和 run 详情支持 `--limit <1–100>`、`--cursor <cursor>`，返回的下一页命令保留过滤条件与页大小。
所有 ID 属于当前会话；缺失或跨会话 ID 返回错误，不自动选择其它对象。取消用户任务必须明确 Job 处理方式。

命令直接调用统一 Host 方法：`monitor/overview`、`monitor/tasks`、
`monitor/task/read|pause|resume|cancel`、`monitor/jobs`、`monitor/job/read|cancel`、
`monitor/runs`、`monitor/run/read`、`monitor/health`。只读查询不提交 Agent 输入或调用模型。
任务控制先读取当前 revision，再携带稳定请求身份提交；版本冲突直接显示，不静默重试。
原有 Monitor status/list/enable/disable 方法及按 Job 切换自动跟进的开关已移除。

暂停用户任务阻止新增自动推进，但不取消其运行中 Job。聊天中的 Esc/`turn/interrupt` 停止当前回复，
并抑制立即自动重启；Monitor 面板里的 Esc 只关闭面板。取消 Job、关闭终端是独立操作。
`/resume` 用于切换会话；`/monitor task resume` 才是恢复当前会话内的任务。

Job wake 与用户通知分别记录回执，带租约和退避。wake 只是“输入已接受”，不代表研究分析已完成。
Task Controller 在继续执行前核对持久任务与 Job 状态；Agent 仍须检查结果，Monitor 不发布科学结论或修改 Node。

`workspace_manifest.json` 中的规范 `workspace_id` 同时绑定科学状态与 Host
路由；不存在独立的科学身份或直接目录 alias 映射。

## 会话存储

安装级 `var/state/pi/sessions/` 是 Native Pi Harness 使用的唯一 session 存储。
workspace `.pi/sessions` 历史不是受支持的输入，Native runtime 不会 resume 或导入它；持久历史位于 `var/state/pi/sessions/<workspace-id>/<session-id>/session.sqlite`，旁边的 `meta.json` 保存路由元数据。
研究状态应保存在 workspace Research Memory；SQLite durable session 使用 Host 的会话控制接口。

详见[架构](ARCHITECTURE.zh-CN.md)和[安装说明](INSTALLATION.zh-CN.md)。
