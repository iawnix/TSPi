# CoRAgent：Phone 协议改名交接说明

状态：本次更名同步更新服务端和 CoRHub 源码。测试结果以实际验收报告为准；尚未发布或进行实机验收。部署步骤见[切换指南](CORAGENT_CUTOVER.zh-CN.md)。

本说明定义 CoRAgent 0.19 与 CoRHub 0.20 的配套协议。服务端直接采用新名称，不接受旧协议和旧令牌前缀；手机端同步切换，不提供旧协议回退。现有 Pi SDK、Server、Durable 和原生终端继续使用。

## 1. 必须同步的值

| 位置 | 当前值 | 目标值 |
| --- | --- | --- |
| Host initialize 请求/响应 `protocol` | `research-agent-host/2` | `coragent-host/2` |
| WebSocket 子协议 | `research-agent-link.v1` | `coragent-link.v1` |
| 配对响应 `protocol` | `research-agent-link.v1` | `coragent-link.v1` |
| Phone 设备 token 前缀 | `rad_` | `cad_` |
| Host token 前缀 | `rah_` | `cah_`，仅 Host 使用，手机不应取得 |

沿用当前版本数字是因为消息结构和业务语义保持；新的命名空间已经是不兼容协议身份，不意味着与旧值可以混用。

设备 token 的目标校验表达式是 `^cad_[A-Za-z0-9_-]{40,80}$`。Host 对应 `^cah_[A-Za-z0-9_-]{40,80}$`。令牌由服务端随机签发，手机不能给保存的旧 token 替换前缀来转换身份。

## 2. 保留的请求结构

- Link WebSocket 路径：`/v1/link`。
- 认证头：`Authorization: Bearer <device-token>`。
- 配对兑换：`POST /v1/pairings/redeem`。
- 配对请求字段：`code`、`deviceName`。
- 配对响应字段：`relayUrl`、`protocol`、`hostId`、`deviceId`、`deviceName`、`deviceToken`。
- 八位一次性配对码及过期约束保持，具体有效期以服务端合同为准。
- `hostId`、`deviceId` 继续为 UUID；设备 token 绑定对应 Host。
- Host 消息继续是 UTF-8 NDJSON，通过 WebSocket 二进制帧传输。
- 业务方法、`workspace_id`、`session_id`、请求 ID、cursor、epoch、错误和通知的既有语义保持。

新 initialize 请求示意：

```json
{
  "id": "phone-1",
  "method": "initialize",
  "params": {
    "protocol": "coragent-host/2",
    "server_id": "00000000-0000-4000-8000-000000000001",
    "client": { "name": "corhub" }
  }
}
```

这是便于阅读的展开形式；实际传输仍为单行 JSON 加换行符。客户端名称 `corhub` 不属于服务端品牌协议标识，不要求为本次后端改名同步改变。

## 3. 当前手机仓库中的修改位置

相对于 `/home/iaw/project/corhub/apps/mobile/`：

| 文件 | 修改内容 |
| --- | --- |
| `lib/data/host_rpc_client.dart` | Host protocol 常量、Link 子协议、initialize 返回校验和相关错误说明 |
| `lib/data/link_pairing.dart` | 配对响应 protocol 校验；文件名和类名可随客户端重构整理 |
| `lib/models/connection_settings.dart` | 设备 token 正则与旧保存配置的显式失效处理 |
| `lib/data/settings_store.dart` 及设置界面 | 提示旧连接需要重新配对；不伪造新 token、不静默删除用户其他设置 |
| 配对、Host RPC、interop 等测试和 fixtures | 统一新协议/令牌，增加拒绝旧值的场景 |

以上文件位置来自当前源码；后续实际修改前应核对客户端的新基线。品牌文案和文件名称可以单独调整，不能漏掉真正参与握手和校验的常量。

## 4. 切换与验收

1. 服务端先完成新协议和新令牌签发，用确定性测试客户端验证握手、配对、消息、撤销与断线恢复。
2. 提供最终合同 fixtures 和服务端 release 信息给手机端。
3. 手机更新后，使用新的配对码取得 `cad_` 凭据，并验证 Host 身份。
4. 验证新建/附着会话、发送消息、断线重连、重复请求身份、Monitor 显示和设备撤销。
5. 明确拒绝旧协议、旧 token 和错误 Host；不自动降级到旧值。

旧手机无法连接新服务端属于预期切换边界。服务端与客户端需要协调部署。验收应区分确定性测试客户端、真实 Dart 客户端联调与手机实机测试，不互相替代。

协议切换需要重新配对，不能给旧令牌替换前缀来转换身份。

## 5. Monitor 与模型请求的跨端合同

Monitor 使用唯一的 `coragent-host/2` 接口；客户端按 initialize 的 capabilities 展示功能。
旧 `monitor/list`、`monitor/status`、`monitor/enable`、`monitor/disable` 已移除，不提供别名或回退。

- 概览与用户任务：`monitor/overview`、`monitor/tasks`、`monitor/task/read`。
- 用户任务控制：`monitor/task/pause`、`monitor/task/resume`、`monitor/task/cancel`。
- 计算作业：`monitor/jobs`、`monitor/job/read`、`monitor/job/cancel`。
- 执行诊断与健康：`monitor/runs`、`monitor/run/read`、`monitor/health`。

所有请求包含 `workspace_id`、`session_id`；目标身份使用 `user_task_id`、`job_id` 或 `run_id`。
列表支持 `limit`（1–100）和不透明 `cursor`；作业和执行列表可按 `user_task_id` 过滤。
写请求必须携带稳定 `request_id`，用户任务控制还需要当前 `expected_revision`。
取消用户任务必须显式选择 `jobs: "keep"` 或 `jobs: "cancel"`。
状态与控制回执由 SessionWorker 在 Pi durable 中保存，Host 与手机不维护第二份状态机。

概览区分用户任务 `task`、作业 `jobs.items` 和 Pi 执行 `execution`。
内部 generation/tool 执行在用户任务的执行详情中展开，不混入用户任务列表。
查询不会提交模型输入。读取成功后订阅既有 `monitor/event` 作业更新提示；任务执行变化沿用
`session/event`。客户端重连或 epoch 改变时重新读取概览，不另建一套事件重放协议。

`model/select` 使用 `model: {provider, id}`，不发送旧的顶层 `provider/model_id`。
跨仓库 fixture 使用 `apps/agent/host/server.mjs`、`apps/agent/pi/backend.mjs`、
`apps/agent/host/workspace.mjs`，环境变量采用 `CORAGENT_*`。
统一运行入口见 `tools/test/README.md` 的 `phone` 套件。
