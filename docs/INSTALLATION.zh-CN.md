# 安装与运维

[English](INSTALLATION.md) | 简体中文

本指南安装 TSPi Agent 及可选的 TS Web 只读浏览器。TS Phone 是独立的 Flutter
应用。TSPi 本地安装只包含 Host 侧 Link 客户端；公网 TSPi Link Relay 使用独立安装器。

## 前置条件

- Linux、Git 和 Node.js 22.19+。
- Python 3.11+、Conda/Mamba，以及可写的用户安装目录。
- `config/pi-source.json` 指定版本的 Pi 源码 checkout；安装器也可以自动下载并修补。
- 可选的 systemd user 或 system service 和 TS Web 端口。创建受管科学运行时需要
  Conda/Mamba；它不是可选的后端依赖。

启动脚本默认使用公开 HTTPS 仓库；Git 传输中断时会有限重试，仍失败则回退到普通
浅克隆。私有 GitHub 仓库可显式传入 SSH 地址，不需要 TS Phone 仓库：

```bash
./install.sh --tspi-repo git@github.com:your-org/TSPi.git
```

## 安装或选择版本

运行 `./install.sh`，确认安装目录、TSPi revision、workspace root、Conda root、
可选 TS Web 组件和服务策略。Core Agent、科学运行时和分子渲染工具始终安装。
非交互安装可使用 `--workspace-root /absolute/path`；默认值为
`<install>/workspaces`。Host、终端、TS Web 和卸载器共享
`.pi/tspi/workspace-root.json` 中记录的值。

交互安装器中的 `Review and install` 会显示完整安装计划。按 Enter 或输入 `Y` 开始安装；
输入 `N` 会返回配置菜单继续修改，尚未写入安装文件或启动服务。选择 `9) Quit` 才会退出
安装器并保持未安装状态。

发布通过以下选择器原子切换：

```text
<install>/.pi/packages/tspi/current -> releases/<release-id>
```

只有选中的 release 会暴露给 `TSPi` 启动器；安装器记录校验和，不执行该 release
之外的源码。

### 可选模型图标字体

可选模型图标字体可通过 `--with-model-icons` 安装，使用
`--without-model-icons` 禁用。字体属于用户数据目录，不是科学运行时依赖；
`TSPI_ICON_STYLE=unicode` 或 `nerd` 可显式覆盖选择。模型字形使用补充私用区，避免被
终端主 Nerd Font 中已有的同码位字形遮蔽。

交互安装默认询问并选择启用；非交互安装默认禁用，明确传入参数才会安装：

```bash
./install.sh --non-interactive --yes --with-model-icons \
  --install-root "$HOME/.local/share/tspi"
```

字体安装在用户数据目录（`$XDG_DATA_HOME/fonts/tspi` 或
`$HOME/.local/share/fonts/tspi`），所选 release 在
`<install>/.pi/tspi/model-icons.json` 保存私有标记。无需另装 Nerd Font；其他图标沿用
已有 Nerd Font，设置 `TSPI_ICON_STYLE=unicode` 时回退到普通 Unicode。安装器在可用时刷新
fontconfig 缓存；已打开的终端可能需要重启才能加载回退字体。

## 受管 Python 运行时

运行时位于 `<install>/.agents/envs/tspi`，元数据位于
`<install>/.agents/runtime/tspi`；缓存位于 `<install>/.pi/runtime-cache`，可删除后
重建而不会影响工作区。运行时探针会检查反应解析、ASE 热模型、几何和渲染。
固定版本的 Pi 源码还需要模型数据和 workspace build 产物，缺失时运行：

```bash
scripts/prepare_pi_source.py --install <root>
```

能力发现、Node 暂停/恢复和选择性远程或模型 smoke 命令见
[科学能力运维](SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md)。升级时同一步也会验证完整的
多工作区补丁；已有项目列表功能的旧安装会在 Host 重启前获得兼容的项目创建和
`workspaceId` session 绑定增量补丁。

## 配置计算后端

本地计算在持久化 Attempt 子进程中执行；远程执行临时镜像输入并将结果收回本地。
两者共享 `compute.run` 的公开生命周期；选择 `execution_target.kind = "local"` 或
`"remote"`，并在计算意图中填写统一配置文件里的环境名。只有 remote 环境包含 SSH/Torque
传输字段。安装器统一接收一份计算后端 TOML 文件：
交互安装时在提示处输入文件路径，非交互安装时使用
`--compute-config /absolute/path/compute.toml`。项目模板位于
`config/compute.example.toml`；复制后按目标机器修改 local/remote environment 及其 backend
绑定，再交给安装器。
安装后的文件为 `<install>/.pi/compute.toml`，权限为 `0600`。

`/compute` 和 `compute.environments` 会列出已配置的本地与远端环境，
TSPi 不会下载 Gaussian 或其他站点管理的本地化学软件，SSH 凭据仍由 SSH
配置管理，不会复制到该 TOML 文件中。

添加 `--probe-remote` 时，安装过程会运行 `TSPi --check-remote`；若 SSH、scheduler、
可写远程根目录或软件探针未就绪，安装会失败。不添加该参数时，摘要只报告 `not_probed`，
不会把远程环境误报为可用：

```bash
./TSPi --check-remote
```

当前远程合同只支持 Torque/PBS。配置必须声明 SSH、可写远程根目录、允许队列及站点
管理的 Gaussian/xTB/CREST/ASE-NEB 命令；配置文件应保持 `0600`。执行层会在准备远端
计算时完成必要的就绪性检查；交互查看配置使用 `/compute`。远程执行代码和软件环境属于
配置的计算节点；App Server 只提交并记录作业，不会把凭据复制到手机端。

## 安装日志

每次安装或更新都会在 `<install>/.pi/logs/install.YYYY.MM.DD.log` 保存仅所有者可读的诊断
日志。同一天重复运行会用 UTC 分隔线追加。日志记录安装器输出、所选路径、release 和服务
状态、后端配置状态及失败详情，但不会记录 TS Web token、SMTP 授权码或 SSH 密钥。失败的
package 步骤还会在同一目录保留独立的 `install-failure-<timestamp>.log`。

## 配置通知

可选邮件通知配置在 `<install>/.pi/notifications.toml`，权限为 `0600`。启动 App Server
前，启动器会验证收件人和传输方式；不创建该文件即可禁用通知。

已有 ClawEmail 安装仍受支持。直接 SMTP 投递时必须使用 163 或 QQ 邮箱的 SMTP 授权码，
不能使用网页登录密码；授权码应保存在配置文件之外。

交互式 `install.sh` 会询问是否配置邮件；非交互安装可显式提供同一配置：

```bash
./install.sh \
  --install-root "$HOME/.local/share/tspi" \
  --non-interactive --yes --service-scope user \
  --email-binding smtp --email-preset qq \
  --email-recipient receiver@example.com \
  --email-address sender@qq.com \
  --email-password-file "$HOME/.config/tspi/qq-smtp-password"
```

非交互安装要求密码文件已经存在且权限为 `0600`。交互流程会隐藏输入授权码，并在私有安装
状态目录下自动创建文件。Host 服务环境提供密钥时，也可改用 `--email-password-env NAME`：

```toml
[notifications.email]
enabled = true
provider = "smtp"
preset = "qq"                 # "163"、"qq" 或 "custom"
recipient = "receiver@example.com"
username = "sender@qq.com"
password_env = "TSPI_EMAIL_PASSWORD"
```

SMTP 预设默认使用 `smtp.163.com` 或 `smtp.qq.com`、465 端口和隐式 TLS。自定义服务器可用
`--email-preset custom --email-host mail.example.org`，并配合 `--email-port` 和
`--email-security`。使用 `--email-password-env NAME` 时，若安装环境中存在该变量，安装器
会创建私有 systemd `EnvironmentFile`；否则请在启动 Host 前创建
`<install>/.pi/email/service.env`。使用私有的 `0600` `password_file` 可免去服务环境配置。
TSPi 通知只发送邮件，不需要 POP3 或 IMAP。

## 启动安装级 Host

一个安装为 workspace root 下所有已验证工作区拥有唯一 TSPi Host。Host 是 control plane；
安装级 Pi App Server 为每个活动 session 管理一个固定版本的 `SessionWorker`/`AgentHarness`
lane。安装器可以启用并启动 Host；普通终端启动时也会按需启动已配置的服务：

```bash
./TSPi --workspace reaction-a
```

user scope 安装使用：

```bash
systemctl --user status ts-app-server-tspi.service
systemctl --user restart ts-app-server-tspi.service
systemctl --user stop ts-app-server-tspi.service
```

system scope 安装省略 `--user`。`service scope = none` 时不管理 Host，Phone 和后台 Monitor
不可用；需要 Host 功能时请选择 user 或 system。生成的 unit 调用 TSPi 内部服务入口，普通
用户不应运行 `TSPi --host`。

默认且推荐的 scope 是 systemd user unit。system unit 必须提供显式的 `--service-user`；安装器
会设置 `HOME`、`PI_CODING_AGENT_DIR` 和私有运行时目录，确保 Host 身份和本地 Pi 连接使用
服务账户。Host worker facet、server-extension allowlist 和 native client 都来自已验证的
Package release。

创建新会话或继续项目中的最新会话：

```bash
./TSPi --workspace reaction-a
./TSPi --workspace reaction-a -c
```

Host 身份位于 `<install>/.pi/app-server-host/server-id`；请求回执、scheduler lease、
Monitor 健康状态和规范 Pi format-4 session repository 也位于同一目录。format-4 文件按 cwd
归档在 `.pi/app-server-host/sessions/`；Native Pi Harness 不接受 workspace `.pi/sessions`。
工作区必须是配置的 workspace root 下、经过验证的直接子目录。

默认终端通过 Host 返回的本地 descriptor 使用 Pi 官方 native remote client，不需要 tmux 或
PTY scraping。Host 重启会保留 format-4 transcript、operation/queue ID、回执和 Monitor outbox；
重新连接的客户端从新的 Host epoch/cursor 恢复。

TS Phone 通过 TSPi Link 连接该 Host。安装时启用 Phone access，并提供 HTTPS TSPi Link Relay
origin 和 Relay 管理员创建的一次性 Host enrollment code。交互式安装会在耗时的运行时安装
完成后、写入 Phone manifest 前才询问这个短期 code，避免安装超过 code 有效期；非交互式安装
仍通过 `--link-enrollment-code` 直接提供。安装器写入
`.pi/app-server-host/link.json` 及仅所有者可读的 `.pi/app-server-host/host.token`；Host
只向 Relay 建立出站 WSS，不会向 Relay 或互联网暴露 App Server 端口。

Host 上线后使用以下命令管理 Phone 授权：

```bash
./TSPi phone pair
./TSPi phone devices
./TSPi phone revoke <device-id>
```

`phone pair` 输出已配置的 Relay URL 和八位配对码。配对码五分钟后失效且只能使用一次；TS
Phone 将其兑换为平台安全存储中的可撤销设备凭据。Phone 凭据、Host token 和 TS Web HTTP
token 相互独立。Phone 是普通的交互式 Pi 客户端，与终端共享同一 Harness lane 和工具；TS Web
仅是只读客户端。

## Monitor 运维

Host 为 workspace root 启动一个 Monitor worker，轮询持久化 Compute 状态，并在每个
workspace 内写入 registration、event 和 delivery 回执。`monitor/list`、`monitor/status`、
`monitor/enable`、`monitor/disable` 提供健康状态和积压信息。wake 与 notification 分别
确认、租约和退避；wake 只表示 Pi 接受了输入，不表示 agent turn 已完成。Root Agent
必须重新读取 `research.read`、检查计算后才能修改 ResearchMap。

`workspace.json` 中稳定的 `ws_<hex>` 身份会先被验证，再映射到 Host 使用的直接目录名，
防止 foreign event 投递到错误项目。

## 会话历史

Native Pi Harness 只接受安装级 `.pi/app-server-host/sessions/` 下的 format-4 session。
旧 workspace 历史文件不会导入或恢复；研究连续性应保存在 Research Memory，而不是第二套
session 格式。

## 工作区初始化

首次运行 `./TSPi --workspace <name>` 时，客户端会在配置的 workspace root 下创建 0700 工作区
及规范科学文件。Host 的 WorkspaceDirectory 也提供同一操作给 TS Phone。Host 不会创建无名项目；
初始化会验证已有 JSON，遇到不支持的状态时拒绝而不是重写。

## 运行 TS Web Research Explorer

安装时选择 TS Web 后，可使用只读浏览器：

```bash
./TSWeb serve \
  --state-dir .pi/ts-web-state \
  --auth-token-file "$HOME/.local/share/tspi/.pi/ts-web/auth.token" \
  --source-root /configured/workspace-root/reaction-a \
  --label "Reaction A" --host 127.0.0.1 --port 8766
```

只有在使用认证 token 文件时，才允许安装配置 `--web-host 0.0.0.0 --allow-remote`；直接运行
TS Web 时对应 `serve --host 0.0.0.0 --allow-remote`。安装器会拒绝缺少这两个显式设置的
非回环绑定。TS Web 只读，既不拥有 Pi session，也不提供科学写入路由。
其 bearer token 与 TSPi Link Host 和 Phone 设备凭据分开。

token 文件不存在时，安装器会生成随机 TS Web token。也可以传入 8--100 个 URL-safe 字符的
`--web-auth-token`，或在交互隐藏提示中输入。命令行 token 可能出现在 shell history 或进程
列表中，生产环境应预先创建 `0600` token 文件并使用 `--web-auth-token-file`。

## 模型配置

模型目录和 API adapter 由固定 Pi release 提供。安装时，安装器会把 Host 服务账户
`~/.pi/agent/` 中已有且安装目录缺失的 `models.json` 与 `auth.json` 复制到私有安装状态
`<install>/.pi/agent/`；升级不会覆盖安装目录中已有的文件。如果没有可导入的配置，必须先
通过 Pi 或 provider 环境变量配置凭据，再创建 TSPi 会话。终端、TS Phone 和其他客户端连接
同一 session，因此共享模型和工具集合；模型兼容性见
[模型兼容性](MODEL_COMPATIBILITY.zh-CN.md)。

## 升级、回滚和恢复

再次运行 `./install.sh` 并选择相同安装根目录。安装器下载或构建新的 content-addressed release，
验证 package inventory，再原子切换 `.pi/packages/tspi/current`。已有 workspace、App Server
identity 和 TS Web credential 会保留。
启动器会把固定 Pi checkout 作为 Native client 使用的内部变量 `TSPI_PI_SOURCE` 导出，用户不应
手工设置它。如果旧 release 报告 `TSPI_PI_SOURCE is required for the native Pi client`，请升级
该安装；修复后的启动器会根据 `config/pi-source.json` 自动选择
`<install>/.pi/runtime-cache/pi` 中的固定 checkout。

升级失败时，安装器会事务性恢复旧 release、launcher、runtime manifest、凭据、backend 文件、
Phone manifest 和受管 service unit。当前 CLI 没有单独的 rollback selector；要切换到旧版本，
用目标 pinned revision 再执行一次正常且经过验证的升级。不要直接编辑 release 目录或手改 `current`
指针。

如果 Host 退出，重启唯一的 Host service。进程退出会释放 Root lock，Pi JSONL session 保持完整。
本地计算 worker 在可用时运行于独立的临时 user service，Host 重启通常不会中断；恢复后仍须检查
Attempt 状态。终端或 Phone 重连时首先接收新的 session snapshot；传输失败且结果不确定时，prompt
不会自动重发。

查看 `<install>/.pi/logs/` 中最新的安装日志，并按安装时的 scope 检查服务：

```bash
systemctl --user status ts-app-server-tspi.service  # user scope
systemctl status ts-app-server-tspi.service         # system scope
```

## 卸载

运行 `./uninstall.sh`。默认保留配置的 workspace root、Pi session history、凭据和配置；删除安装
根目录必须显式确认。卸载器还会在配置的 scope 中停止并删除匹配的 App Server 和 TS Web service。
独立的 Link Relay 具有自己的安装和 service 生命周期，不会被本地 TSPi 卸载器删除。
