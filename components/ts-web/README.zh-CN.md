# TS Web 组件

`@iawnix/ts-web` 是 TSPi 的可选只读浏览器客户端。它负责 HTTP 传输、
浏览器资源、工作区注册命令和投影客户端，不导入 `ts_agent`，也不拥有
科研状态。

该组件通过版本化的 `ts-web-provider/1` JSON-lines 协议与 TSPi Agent 通信。
物理工作区位置由 TSPi 保存并由核心计算投影，Web 响应只包含逻辑工作区数据。

组件以带 manifest 的独立归档发布。TSPi Package 可以不安装它；选择安装时，
安装器将它放在 `current/web/` 下，并创建 `TSWeb` 启动入口。
服务默认绑定 `127.0.0.1`。绑定局域网或公网地址必须显式指定
`--allow-remote`，同时必须通过 `--auth-token-file`（推荐）、
`--auth-token` 或 `TSPI_WEB_AUTH_TOKEN` 提供 token；token 文件必须是
绝对路径、归当前用户所有、权限为 `0600`，且不能是符号链接或硬链接；
跨越不可信网络时还应使用 TLS。
启用 token 后，浏览器会在首次访问时提示输入，并仅在当前页面的内存中保留；
刷新或关闭页面后需要重新输入。token 不会写入 URL 或浏览器持久存储。
