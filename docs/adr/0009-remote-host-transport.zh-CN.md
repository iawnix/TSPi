# ADR 0009：远程 Host 传输与规范工作区状态

## 状态

已接受；SSH 流传输和终端 proxy 链路已经实现。

## 决策

`tspi-host/1` NDJSON RPC 与底层传输解耦。客户端可以使用私有 Unix socket，或通过 SSH 启动
`tspi-host-proxy`，让 proxy 把 stdin/stdout 字节转发到远端 Host Unix socket。Phone 继续使用
TSPi Link 的 WSS Relay。三种方式都使用同一份 Host RPC，不创建第二个 Agent lane。

```text
Client -- SSH stdin/stdout --> tspi-host-proxy -- Unix socket --> TSPi Host
```

远端 Host 所在机器拥有 workspace、SQLite durable session、Research Memory 和 workspace lock，
是唯一权威副本。TSPi 不使用实时双向 rsync 运行 workspace。批量复制工具可以根据
`tspi-artifact-transfer/1` manifest 执行初始化、备份或导出，但不能复制
`.pi/app-server-host/sessions` 或静默替换规范 workspace。manifest 列出每个文件，记录整文件和
分块 SHA-256 digest；接收端通过可恢复的临时文件传输，完成后再原子 rename。

SSH 主机密钥校验、用户认证和跳板机由 OpenSSH 负责；Host 协议认证和 release 协商由 TSPi 负责。
大型 artifact 需要独立的有界、digest 校验和可恢复传输合同。

## 验证

传输覆盖流 framing、SSH 参数校验、Host release 协商、Host 与 Pi App Server socket 的转发，
以及 SSH 或 proxy 退出时的清理。artifact transfer 测试覆盖 manifest 范围、受保护路径、
分块边界、digest 不匹配、断点恢复和幂等重复应用。
