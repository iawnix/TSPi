# TSPi Link

[English](TSPi_LINK.md) | 简体中文

TSPi Link 让 TS Phone 在不暴露 App Server 端口的情况下连接安装级 Host。它只是一层
传输边界，不是第二套应用服务器：

```text
TS Phone -- WSS --> TSPi Relay <-- WSS -- TSPi Host -- Unix socket -- App Server
```

Relay 只管理 Host 注册、Phone 配对、设备撤销和不透明字节转发。workspace、session、
transcript、模型、工具、ResearchMap 和计算状态始终只由 App Server 管理。

## 运行 Relay

安装 Relay 固定版本的依赖，并把运行状态放在源码目录之外：

```bash
npm --prefix services/tspi-relay ci
node services/tspi-relay/cli.mjs serve \
  --state /var/lib/tspi-relay/relay.db \
  --public-url https://link.example.com \
  --listen 127.0.0.1 --port 8788
```

在 loopback 监听端口前配置 TLS 反向代理。代理必须保留 WebSocket upgrade 和请求体，
且不得记录 `Authorization` header 或 Link payload，并应限制 enrollment 与 pairing
端点的请求频率。公网 URL 必须使用 HTTPS；只有 loopback 开发环境允许明文 HTTP。

## 注册 Host

在 Relay 机器上创建有效期十分钟、只能使用一次的 enrollment code：

```bash
node services/tspi-relay/cli.mjs enrollment create \
  --state /var/lib/tspi-relay/relay.db
```

在 Host 上运行 TSPi 安装器，选择 `TSPi Relay` Phone access，并输入 Relay URL 和
enrollment code。安装器把 Host 凭据写入 owner-only 的
`.pi/app-server-host/host.token`。之后 App Server service 会自动维持出站 Link 连接。

## 配对与撤销手机

在已注册的 Host 上运行：

```bash
TSPi phone pair
TSPi phone devices
TSPi phone revoke <device-id>
```

在 TS Phone 中输入 Relay URL 和 8 位配对码。配对码有效期五分钟且只能使用一次。
每台 Phone 都得到独立设备 token，因此撤销一台设备不需要轮换 Host 或其他设备的凭据；
撤销会立即关闭该设备的活动连接。

## 安全边界

Host 和设备 token 都是随机 256-bit 值，Relay 只保存它们的 SHA-256 hash。长期 token
不会进入配对码或 systemd 环境变量。WSS 分别保护两条网络链路，但 Link 1 不增加应用
层端到端加密；Relay 运营者可以观察转发的 App Server 字节，因此应使用可信基础设施
或私有网络。

线协议见 [`contracts/tspi-link/1/README.md`](../contracts/tspi-link/1/README.md)。
