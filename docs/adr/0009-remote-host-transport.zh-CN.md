# ADR 0009：远程 Host 传输与规范工作区状态

## 状态

已接受；SSH 流传输和终端 proxy 链路已经实现。

## 决策

`tspi-host/2` NDJSON RPC 与底层传输解耦。客户端可以使用私有 Unix socket，或通过 SSH 启动
`tspi-host-proxy`，让 proxy 把 stdin/stdout 字节转发到远端 Host Unix socket。Phone 继续使用
TSPi Link 的 WSS Relay。三种方式都使用同一份 Host RPC，不创建第二个 Agent lane。

```text
Client -- SSH stdin/stdout --> tspi-host-proxy -- Unix socket --> TSPi Host
```

远端 Host 所在机器拥有 workspace、SQLite durable session、Research Memory 和 workspace lock，
是唯一权威副本。TSPi 不使用实时双向 rsync 运行 workspace。远程作业的显式文件操作由
运维 shell 负责；artifact 注册仍然独立于传输方式。

SSH 主机密钥校验、用户认证和跳板机由 OpenSSH 负责；Host 协议认证和 release 协商由 TSPi 负责。

## 验证

传输覆盖流 framing、SSH 参数校验、Host release 协商、Host 与 Pi App Server socket 的转发，
以及 SSH 或 proxy 退出时的清理。
