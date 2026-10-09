# ResearchAgent：Phone 协议改名交接说明

状态：服务端和手机源码已对齐此合同；本机自动化联调使用真实 Dart 客户端及 Pi Worker。尚未构建、部署或验证手机设备上的新版应用，不能把本机联调视为实机验收。

本说明配套[重构方案](RESEARCH_AGENT_REFACTOR_PLAN.zh-CN.md)。服务端直接采用新名称，不接受旧协议和旧令牌前缀；手机端由用户后续同步。现有 Pi SDK、Server、Durable 和原生终端继续使用。

## 1. 必须同步的值

| 位置 | 当前值 | 目标值 |
| --- | --- | --- |
| Host initialize 请求/响应 `protocol` | `tspi-host/2` | `research-agent-host/2` |
| WebSocket 子协议 | `tspi-link.v1` | `research-agent-link.v1` |
| 配对响应 `protocol` | `tspi-link.v1` | `research-agent-link.v1` |
| Phone 设备 token 前缀 | `tspd_` | `rad_` |
| Host token 前缀 | `tsph_` | `rah_`，仅 Host 使用，手机不应取得 |

沿用当前版本数字是因为消息结构和业务语义保持；新的命名空间已经是不兼容协议身份，不意味着与旧值可以混用。

设备 token 的目标校验表达式是 `^rad_[A-Za-z0-9_-]{40,80}$`。Host 对应 `^rah_[A-Za-z0-9_-]{40,80}$`。令牌由服务端随机签发，手机不能给保存的旧 token 替换前缀来转换身份。

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
    "protocol": "research-agent-host/2",
    "server_id": "00000000-0000-4000-8000-000000000001",
    "client": { "name": "ts-phone" }
  }
}
```

这是便于阅读的展开形式；实际传输仍为单行 JSON 加换行符。客户端名称 `ts-phone` 不属于服务端品牌协议标识，不要求为本次后端改名同步改变。

## 3. 当前手机仓库中的修改位置

相对于 `/home/iaw/project/ts-phone/apps/mobile/`：

| 文件 | 修改内容 |
| --- | --- |
| `lib/data/host_rpc_client.dart` | Host protocol 常量、Link 子协议、initialize 返回校验和相关错误说明 |
| `lib/data/tspi_link_pairing.dart` | 配对响应 protocol 校验；文件名和类名可随客户端重构整理 |
| `lib/models/connection_settings.dart` | 设备 token 正则与旧保存配置的显式失效处理 |
| `lib/data/settings_store.dart` 及设置界面 | 提示旧连接需要重新配对；不伪造新 token、不静默删除用户其他设置 |
| 配对、Host RPC、interop 等测试和 fixtures | 统一新协议/令牌，增加拒绝旧值的场景 |
| 保留的 `pi_app_server_client.dart` | 若继续保留可用入口，同步其 Link 子协议；Pi 自有协议版本不跟随品牌改名 |

以上文件位置来自当前源码；后续实际修改前应核对客户端的新基线。品牌文案和文件名称可以单独调整，不能漏掉真正参与握手和校验的常量。

## 4. 切换与验收

1. 服务端先完成新协议和新令牌签发，用确定性测试客户端验证握手、配对、消息、撤销与断线恢复。
2. 提供最终合同 fixtures 和服务端 release 信息给手机端。
3. 手机更新后，使用新的配对码取得 `rad_` 凭据，并验证 Host 身份。
4. 验证新建/附着会话、发送消息、断线重连、重复请求身份、Monitor 显示和设备撤销。
5. 明确拒绝旧协议、旧 token 和错误 Host；不自动降级到旧值。

旧手机无法连接新服务端属于预期切换边界。服务端重构交付不等待旧手机兼容；真实 Phone 联调完成前，报告中必须标记该项待更新/待联调，不能以测试客户端结果冒充实际手机验收。

协议切换需要重新配对，不能给旧令牌替换前缀来转换身份。

## 5. Monitor 与模型请求的跨端合同

`monitor/list`、`monitor/status` 的 `monitors` 元素为平铺视图，手机直接读取
`last_state`、`pending_count`、`last_observed_at` 和 `last_error`，不再读取旧的
`state`、`delivery` 嵌套对象。后面三个字段由已有事件及投递记录派生，不另存状态。

`monitor/enable`、`monitor/disable` 返回 `{workspace_id, updated}`。手机确认
`updated == 1` 后使用相同 `monitor_id` 调用 `monitor/status`，将返回的视图用于界面；
`updated == 0` 表示目标不存在。不能把更新回执解析为 Monitor。

`model/select` 使用 `model: {provider, id}`，不发送旧的顶层 `provider/model_id`。
跨仓库 fixture 使用 `apps/agent/host/server.mjs`、`apps/agent/pi/backend.mjs`、
`apps/agent/host/workspace.mjs`，环境变量采用 `RESEARCH_AGENT_*`。
统一运行入口见 `tools/test/README.md` 的 `phone` 套件。
