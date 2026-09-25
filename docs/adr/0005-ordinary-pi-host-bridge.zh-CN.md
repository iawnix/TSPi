# ADR 0005：普通 Pi Runtime 与 Host Bridge

[English](0005-ordinary-pi-host-bridge.md) | 简体中文

- 状态：已退役；仅作为历史设计记录
- 日期：2026-09-21
- 范围：TSPi 启动器、Pi 终端、Host、Phone、Web、Monitor 与历史

## 决定

本 ADR 记录过去的普通 Pi 兼容模式。该模式已经退役，不会被当前运行时选择、打包或访问。
历史上只有显式设置
`TSPI_HOST_BACKEND=ordinary` 时，`TSPi --workspace <name>` 才启动固定版本 Pi CLI 的
普通 `InteractiveMode`。Pi 拥有 agent loop、模型、工具、format-3 transcript、cwd 和
workspace Root lock。TSPi 只加载普通研究 extension 及一个很小的 bridge extension；
该模式有独立 writer，绝不能作为 Harness fallback。

默认运行时是 Harness 架构中的安装级 Pi App Server：一个
`SessionWorker`/`AgentHarness` lane 由 Pi 原生 remote TUI、Phone 和 Monitor 共同使用。

安装级 Host 是 control plane，不是第二个 Pi runtime。它在私有 Unix socket 上提供
认证的 `tspi-host/1` NDJSON，负责 workspace/session 发现、输入接收、幂等回执、事件
订阅、模型选择和 Monitor supervisor。bridge 把 Host 请求转给正在运行的 Pi
ExtensionAPI，再把 Pi 的 snapshot/event 发布回来。每个 workspace 只允许一个 live Pi
进程。

普通兼容模式可以把 `tmux` 作为持久化边界，但这只属于显式迁移/调试流程。Harness
路径绝不启动 tmux，也不抓取 PTY；兼容模式无法使用 tmux 时可以前台运行 Pi，但该进程
不得写入 Harness format-4 repository。

TS Phone 通过 TSPi Link 使用 Host RPC。Relay 只转发不透明的 NDJSON 帧，不拥有
session 或科学状态。可选 browser gateway 只是附着一个现有 Host session 的 loopback
适配器。

Host 为 workspace root 启动一个 Monitor worker。Monitor 持久化 registration、event 和
按通道 delivery 回执；wake 与 notification 独立确认，带租约、重试和去重。wake 被接受
不代表 agent 已完成；Monitor 不会自动 finalize 或写 ResearchMap。

科学 `workspace.json` 身份（`ws_<hex>`）与 Host 路由身份（直接子目录名）分离。worker
必须先验证归属，再做两者转换。

兼容历史不会被静默转换，也不会以可写方式打开。Host 只读列出 workspace format-3
文件；显式 import 会创建新的安装级 format-4 session，保留源文件并写入 provenance
报告。活动、残缺、有歧义或不支持的历史会拒绝。

## 后果

- Pi 原生命令和行为完整保留，不引入 TSPi 自己的渲染器。
- Phone、Web、Monitor 可以共享一个 live Pi session，不拥有第二个 agent。
- `request_id` 和 `client_message_id` 让重试可观察；不确定输入不会盲目重放。
- 兼容模式与 Harness 的回执、历史和锁完全隔离；实现已从受支持运行时移除。
- 默认 Harness 终端不依赖 tmux，Host 恢复后通过本地 Pi connection descriptor 重新连接。
