# TS Web 组件

`@iawnix/ts-web` 是 TSPi 的可选只读浏览器客户端。它负责 HTTP 传输、
浏览器资源、工作区注册命令和投影客户端，不导入 `ts_agent`，也不拥有
科研状态。

该组件通过版本化的 `ts-web-provider/1` JSON-lines 协议与 TSPi Agent 通信。
物理工作区位置由 TSPi 保存并由核心计算投影，Web 响应只包含逻辑工作区数据。

组件以带 manifest 的独立归档发布。TSPi Package 可以不安装它；选择安装时，
安装器将它放在 `current/web/` 下，并创建 `TSWeb` 启动入口。
服务默认绑定 `127.0.0.1`。绑定局域网或公网地址必须显式指定
`--allow-remote`，并由部署方负责认证和 TLS。
