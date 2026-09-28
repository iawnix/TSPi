# ADR 0008：Research Agent 独立 APP 布局

- 状态：提案
- 日期：2026-09-27
- 范围：安装、release 激活以及客户端/服务端归属

## 决定

Research Agent 按独立 APP 安装。Pi 只是私有 Runtime Adapter，不是安装边界，也不是
公共入口。Server、Worker、Launcher 和客户端握手必须使用唯一的活动 release 身份。

目标布局：

```text
/home/iaw/ResearchAgent/
  bin/ResearchAgent             # 稳定的用户 CLI/TUI 入口
  bin/ResearchAgentServer       # 稳定的 App Server 入口
  bin/TSWeb                      # 可选浏览器客户端入口
  releases/<release-id>/         # 不可变 APP release
  current -> releases/<release-id>
  etc/                           # 配置和 owner-only 密钥
  var/workspaces/                # 工作区数据
  var/sessions/                  # 持久 Session 元数据
  var/artifacts/                 # 共享 Capability ArtifactStore
  var/runtime/pi/<commit>/       # 固定版本的 Pi Adapter/runtime cache
  var/log/                       # 服务日志
  var/locks/                     # 安装与激活锁
```

旧 `.pi/packages/tspi` 目录只作为迁移来源。新布局激活后，生产组件不能再解析归档的
`ts-agent` 或 `tspi` release。稳定 shim 在进程启动时解析 `current` 并导出
`release_id`；单个进程不能混用两个 release 根目录的模块。

## 激活协议

更新时先获取安装锁，标记 maintenance，排空或停止受管 App Server，原子切换
`current`，执行 release 健康检查，重启服务，最后清除 maintenance。服务发布活动
release ID 和 epoch。TUI/Phone 收到已关闭 epoch 后返回可重连错误并重新附着 Session，
不能继续使用失效的 `pi.agent-controller` binding。

## 后果

- `ResearchAgent` 是产品入口；`ResearchAgentServer` 是控制平面进程；`TSWeb` 是可选客户端。
- 配置、状态、runtime 和 workspace 具有独立的归属与备份边界。
- Pi 升级属于 Adapter release 变更，不改变 Research Agent 的公共包身份。
- 安装测试必须确认所有 shim、systemd unit、Worker 和选中 package 报告同一 release ID，
  并拒绝归档路径。
