# TSPi Link

[English](TSPi_LINK.md) | 简体中文

TSPi Link 让 TS Phone 在不暴露 Pi 或 Host 公网端口的情况下连接安装级 Host。它只是一层
传输边界，不是第二套应用服务器：

```text
TS Phone -- WSS --> TSPi Link Relay <-- WSS -- TSPi Host -- Unix socket -- Pi App Server / Harness
```

Relay 只管理 Host 注册、Phone 配对、设备撤销和不透明帧转发。Host 管理路由与客户端
访问；Pi Harness worker 拥有 session、transcript、模型和工具。Relay 不拥有 workspace、
ResearchMap 或计算状态。

## 安装 TSPi Link Relay

TSPi Link Relay 是部署在公网或私有网络节点上的独立服务，不由本地 TSPi Host 安装器
安装。在 Relay 机器上的 TSPi checkout 中运行：

```bash
./install-link-relay.sh \
  --public-url https://link.example.com \
  --listen 127.0.0.1 --port 8788 \
  --service-scope system --enable-services --start-services
```

安装器会创建 `tspi-link-relay.service`，在独立安装目录中安装锁定的 npm 依赖，把 SQLite
状态保存到 `/var/lib/tspi-link-relay`，并输出一次性的 Host enrollment code。loopback
监听器前还需要单独配置 TLS 反向代理。代理必须保留 WebSocket upgrade 和请求体，不得
记录 `Authorization` header 或 Link payload，并应限制 enrollment 与 pairing 端点的请求频率。

公网 URL 必须使用 HTTPS；只有 loopback 开发环境允许明文 HTTP。

删除独立服务时，卸载器会停止并移除 service 注册；默认保留已注册 Host、Phone
和设备凭据：

```bash
./uninstall-link-relay.sh --service-scope system --non-interactive --yes
```

只有明确加入 `--purge-state` 时，才会删除 Relay 数据库以及全部注册凭据。

## 注册 Host

安装器会输出有效期十分钟、只能使用一次的 enrollment code。之后可以用已安装的 CLI
生成新的 code：

```bash
node /opt/tspi-link-relay/current/service/cli.mjs enrollment create \
  --state /var/lib/tspi-link-relay/relay.db
```

在 Host 上运行 TSPi 安装器，选择 `TSPi Link Relay` Phone access，并输入 Relay URL 和
enrollment code。安装器把 Host 凭据写入 owner-only 的
`.pi/app-server-host/host.token`。之后 Host service 会自动维持出站 Link 连接。

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
层端到端加密；Relay 运营者可以观察转发的 `tspi-host/1` NDJSON，因此应使用可信基础设施
或私有网络。

线协议见 [`contracts/tspi-link/1/README.md`](../contracts/tspi-link/1/README.md)。
