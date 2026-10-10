# 安装与运维

[English](INSTALLATION.md) | 简体中文

本指南安装 ResearchAgent Agent、可选的 TS Web 只读浏览器，以及按需安装的公网 ResearchAgent Link Relay。
TS Phone 是独立的 Flutter 应用。Relay 仍然是独立服务和独立安装目录，但主安装器可以
在一次安装中部署 Relay 并完成 Host 注册。

## 前置条件

- Linux、Git 和 Node.js 22.19+。
- Python 3.11+、Conda/Mamba，以及可写的用户安装目录。
- `config/pi-source.json` 指定版本的 Pi 源码 checkout；安装器也可以自动下载并修补。
- 正常安装需要 systemd user 或 system service；TS Web 端口是可选的。创建受管控制运行时需要
  Conda/Mamba；它不是可选的后端依赖。

启动脚本默认使用公开 HTTPS 仓库；Git 传输中断时会有限重试，仍失败则回退到普通
浅克隆。私有 GitHub 仓库可显式传入 SSH 地址，不需要 TS Phone 仓库：

```bash
./install.sh --research-agent-repo git@github.com:your-org/ResearchAgent.git
```

## 安装或选择版本

运行 `./install.sh`，确认安装目录、ResearchAgent revision、workspace root、Conda root、
可选 TS Web 组件和服务策略。Core Agent 和控制运行时始终安装；首次安装没有提供
job.toml 时，还会自动准备本地 structure/validation 环境。其他科研环境显式选择，
已有绑定保持不变。

根目录只提供 `install.sh` 和 `uninstall.sh` 两个入口。`install.sh` 默认从 GitHub
选择版本；`--source local` 使用当前 checkout，`--source-root /绝对路径` 可选择另一个
本地 checkout。GitHub 分支、标签或提交由 `--research-agent-ref` 选择。本地安装使用 HEAD，
未提交修改默认拒绝；本机验证可显式使用 `--allow-dirty`。

统一的配置目录入口为：

```bash
./install.sh --source local --config-dir "$PWD/config" \
  --install-root "$HOME/ResearchAgent" --non-interactive --yes
```

配置目录可提供 `job.toml`、`models.json`、`auth.json`、`email.toml` 和
`name-resolver.toml`；没有的配置沿用安装器默认值或已有安装状态。命令行参数优先于
`RESEARCH_AGENT_*` 环境默认值和配置目录。添加 `--dry-run` 可查看脱敏计划，不下载、
复制凭据或启动服务。GitHub 安装也从调用者指定的本机目录读取凭据，不会把该目录上传。

Phone/Relay 不会自动启用。需要本机 Relay 时，显式传入 `--with-link-relay --link-url https://你的域名`。
安装器在 Core 安装后部署或复用 Relay，获取一次性 enrollment code 并完成 Host 注册。
默认 Relay 代码位于 `<install>/runtimes/link-relay`，状态位于 `<install>/var/state/link-relay`。
可用 `--link-relay-root`、`--relay-state-dir`、`--relay-listen`、`--relay-port` 和
`--relay-service-scope` 配置。新建的 loopback Relay 使用本地地址兑换 enrollment code；
可用 `--link-enrollment-url` 覆盖。已有外部 Relay 时，使用
`--phone-access link --link-url https://你的域名 --link-enrollment-code <code>`。
单独安装和卸载使用 `./install.sh relay`、`./uninstall.sh relay`，选项见各自的 `--help`。

非交互安装可使用 `--workspace-root /absolute/path`；默认值为
`<install>/workspaces`。Host、终端、TS Web 和卸载器共享
`etc/installation.json` 中记录的值。

交互安装器中的 `Review and install` 会显示完整安装计划。按 Enter 或输入 `Y` 开始安装；
输入 `N` 会返回配置菜单继续修改，尚未写入安装文件或启动服务。选择 `9) Quit` 才会退出
安装器并保持未安装状态。

发布通过以下选择器原子切换：

```text
<install>/current -> releases/<release-id>
```

只有选中的 release 会暴露给 `ResearchAgent` 启动器；安装器记录校验和，不执行该 release
之外的源码。

### 可选模型图标字体

可选模型图标字体可通过 `--with-model-icons` 安装，使用
`--without-model-icons` 禁用。字体属于用户数据目录，不是科学运行时依赖；
`RESEARCH_AGENT_ICON_STYLE=unicode` 或 `nerd` 可显式覆盖选择。模型字形使用补充私用区，避免被
终端主 Nerd Font 中已有的同码位字形遮蔽。

交互安装默认询问并选择启用；非交互安装默认禁用，明确传入参数才会安装：

```bash
./install.sh --non-interactive --yes --with-model-icons \
  --install-root "$HOME/.local/share/research-agent"
```

字体安装在用户数据目录（`$XDG_DATA_HOME/fonts/research-agent` 或
`$HOME/.local/share/fonts/research-agent`），所选 release 在
`<install>/etc/model-icons.json` 保存私有标记。无需另装 Nerd Font；其他图标沿用
已有 Nerd Font，设置 `RESEARCH_AGENT_ICON_STYLE=unicode` 时回退到普通 Unicode。安装器在可用时刷新
fontconfig 缓存；已打开的终端可能需要重启才能加载回退字体。

## 受管 Python 运行时

Host Python 环境默认位于 `~/soft/research-agent/host-envs/<installation-id>`，元数据位于
`<install>/var/state/installation/python`；缓存位于 `<install>/var/cache`，可删除后
重建而不会影响工作区。Host 通过 `environment.lock.txt` 安装固定 Conda 构建，
不按 `environment.yml` 重新求解。基础环境身份包含 YAML 和显式锁摘要，Python overlay
身份同时绑定基础环境和发行代码。Host 探针检查 JSON Schema、版本约束和 wheel 来源；
科学依赖由扩展执行入口声明，在 `job.toml` 绑定的本地或远程目标检查。
固定版本的 Pi 源码还需要模型数据和 workspace build 产物，缺失时运行：

```bash
scripts/prepare_pi_source.py --install <root>
```

能力发现、Job 取消与恢复和选择性远程或模型 smoke 命令见
[科学能力运维](SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md)。同一步会验证固定版本的 Pi
运行时及文档列出的 ResearchAgent 补丁集；运行时使用下文说明的按 workspace 隔离的 SQLite session
布局。

## 配置计算后端

本地 Job 运行在独立 systemd 用户服务中；SSH/Torque 或 PBS 目标暂存输入并回收声明
输出。所有目标使用 `job_start/job_status/job_collect`，由 Job 的 `platform` 字段选择
已配置环境，不隐式添加本地回退或 remote 别名。

复制 `config/job.example.toml` 并修改目标路径与绑定，再通过
`--job-config /absolute/path/job.toml` 交给安装器。安装管理的私有副本位于
`<install>/etc/job.toml`。SSH 凭据仍保留在 SSH 配置中。ResearchAgent 不安装站点管理的
Gaussian 或 xTB 原生程序。

主安装器根据 domain 的 `environments/manifest.json` 自动准备科研环境。首次安装没有
`job.toml` 时，默认建立本地 `structure`（RDKit/NumPy，与 validation 共用）环境。
已有绑定保持有效；可显式选择 `pyscf`、`render`，或为已有 Gaussian/xTB 绑定准备 `wrapper`。
原生 Gaussian/xTB 软件需在目标机器上预先安装。

```bash
./install.sh --source local --install-root "$HOME/ResearchAgent" \
  --job-profile local:structure --job-profile local:pyscf \
  --job-software-root local=/home/iaw/soft/research-agent/job-envs/my-install \
  --non-interactive --yes
```

本地环境默认位于 `~/soft/research-agent/job-envs/<installation-id>`。
`--without-default-job-environment` 可创建仅含控制服务的新安装。
`--job-offline` 使用预先准备的 Conda/pip 缓存。相同依赖直接复用，锁文件更新时创建新前缀。
用户修改过的绑定仅核验，不覆盖；锁文件和回执保存在目标的持久目录。

配置了名为 cluster 的 SSH 目标后，可增加：

```bash
--job-config /absolute/job.toml --job-profile cluster:structure \
--job-software-root cluster=/remote/shared/research-agent/envs \
--job-conda cluster=/remote/conda/bin/conda
```

远端目录必须能被计算节点访问。SSH 主机需要 Python 3.11+、Conda 和 timeout，
Job 使用已配置的 PBS/Torque 队列。仅传输安装 helper、锁及所选目标绑定，不传输
Host 的模型或邮件凭据；生成的解析缓存使用远端路径。当前锁支持 Linux x86_64：
科研/渲染环境要求 glibc >=2.28，wrapper >=2.17。离线目标需要预先准备依赖缓存。

本地目标自动验收；选择远端 profile 会准备并验收该目标。
`--verify-job-target cluster` 可验收已有远端绑定。其余远端保留配置，报告为
`not_verified`，不发起 SSH。`--job-check-timeout` 限制每个验收 Job 的总等待时间，
包括排队，默认 180 秒。验收通过普通 Job 执行结构检查、XYZ 生成及相应后端的小型
计算/渲染，收集结果；远端目录只在终止或确认取消后清理。取消未完成会使验收失败，
保留 Job 回执供后续处理。

结果分别记录配置、环境和执行检查。PubChem/OPSIN 的联网状态记为 `not_checked`；
安装的离线验收不调用名称服务、模型或发送邮件。默认在本地准备结构，再送到远端计算。
运行绑定仍在 `etc/job.toml`，归属与验收记录保存在
`var/state/installation/job-environments.json` 和 `job-readiness.json`。
维护时仍可运行模块导入和版本探测：

```bash
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.environment_check --config "$RESEARCH_AGENT_JOB_CONFIG"
```

完整发布包也使用相同流程，无需下载源码：

```bash
./install.sh --source package --package-manifest /absolute/research-agent-package-release.json \
  --install-root "$HOME/ResearchAgent" --non-interactive --yes
```

## 安装日志

每次安装或更新都会在 `<install>/var/log/install.YYYY.MM.DD.log` 保存仅所有者可读的诊断
日志。同一天重复运行会用 UTC 分隔线追加。日志记录安装器输出、所选路径、release 和服务
状态、后端配置状态及失败详情，但不会记录 TS Web token、SMTP 授权码或 SSH 密钥。失败的
package 步骤还会在同一目录保留独立的 `install-failure-<timestamp>.log`。

## 配置通知

可选邮件通知配置在 `<install>/etc/email.toml`，权限为 `0600`。启动 App Server
前，启动器会验证收件人和传输方式；不创建该文件即可禁用通知。

使用 `./install.sh --config-dir /绝对路径/config` 时，邮件设置来自该目录的
`email.toml`，格式见 `config/email.example.toml`；不再内置发件人或收件人。授权码由
`password_file` 或 `password_env` 引用，文件相对路径以配置目录为基准。缺少该文件或
`enabled = false` 时不传入邮件设置，新安装不启用邮件，更新保留已有设置。
模型凭据示例及私有配置保护说明见 [config/README.md](../config/README.md)。

已有 ClawEmail 安装仍受支持。直接 SMTP 投递时必须使用 163 或 QQ 邮箱的 SMTP 授权码，
不能使用网页登录密码；授权码应保存在配置文件之外。

交互式 `install.sh` 会询问是否配置邮件；非交互安装可显式提供同一配置：

```bash
./install.sh \
  --install-root "$HOME/.local/share/research-agent" \
  --non-interactive --yes --service-scope user \
  --email-binding smtp --email-preset qq \
  --email-recipient receiver@example.com \
  --email-address sender@qq.com \
  --email-password-file "$HOME/.config/research-agent/qq-smtp-password"
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
password_env = "RESEARCH_AGENT_EMAIL_PASSWORD"
```

SMTP 预设默认使用 `smtp.163.com` 或 `smtp.qq.com`、465 端口和隐式 TLS。自定义服务器可用
`--email-preset custom --email-host mail.example.org`，并配合 `--email-port` 和
`--email-security`。使用 `--email-password-env NAME` 时，若安装环境中存在该变量，安装器
会创建私有 systemd `EnvironmentFile`；否则请在启动 Host 前创建
`<install>/etc/secrets/service.env`。使用私有的 `0600` `password_file` 可免去服务环境配置。
ResearchAgent 通知只发送邮件，不需要 POP3 或 IMAP。

## 启动安装级 Host

一个安装为 workspace root 下所有已验证工作区拥有唯一 ResearchAgent Host。Host 是 control plane；
安装级 Pi App Server 为每个活动 session 管理一个固定版本的 `SessionWorker`/`durable Harness`
lane。安装器会在报告成功前启用并启动 Host；普通终端启动时直接附着到该服务：

```bash
./research-agent --workspace reaction-a
```

user scope 安装使用：

```bash
systemctl --user status ts-app-server-research-agent.service
systemctl --user restart ts-app-server-research-agent.service
systemctl --user stop ts-app-server-research-agent.service
```

system scope 安装省略 `--user`。Host 是终端、Phone 和后台 Monitor 的必需依赖；`service scope = none`
仅用于底层包暂存或测试，普通 workspace 入口不可用。生成的 unit 调用 ResearchAgent 内部服务入口，普通
用户不应运行 `research-agent --host`。

默认且推荐的 scope 是 systemd user unit。system unit 必须提供显式的 `--service-user`；安装器
会设置 `HOME`、`PI_CODING_AGENT_DIR` 和私有运行时目录，确保 Host 身份和本地 Pi 连接使用
服务账户。Host worker、工具装配和 native client 都来自已验证的
Package release。

## 安装器会创建哪些服务

服务列表取决于 scope 和可选组件：

| 组件 | unit | 创建条件 |
| --- | --- | --- |
| ResearchAgent Host | `ts-app-server-research-agent.service` | `--service-scope user` 或 `system` |
| TS Web | `ts-web-research-agent.service` | `--with-web` 且 Host 使用 service scope |
| Link Relay | `research-agent-relay.service` | `--with-link-relay` 且 `--relay-service-scope user` 或 `system` |

使用 `--*-service-scope none` 时只安装文件和配置，不注册对应的 systemd unit。Host
会管理 Monitor 和 session worker，它们不是额外的常驻 unit。TS Phone 是独立的 Flutter
客户端，不会在安装主机上创建服务。

## research-agent 与内部 App Server

`research-agent` 打开连接安装级 Agent Server 的终端。服务由 systemd 管理：

```bash
systemctl --user start ts-app-server-research-agent.service
```

生成的 unit 调用 `current/agent/libexec/research-agent-host` 内部入口，并明确设置安装根目录。
不再提供公开的 `research-agentServer` 命令。
Host API、Pi SDK Harness、Monitor 和 session worker 都属于同一个 Agent Server。
Pi 负责 Agent loop、模型/工具调用和持久 transcript，ResearchAgent 负责研究策略与工具。

固定的 Pi checkout 位于 `<install>/runtimes/pi/<commit>`。Session 存储由安装
统一管理；独立 runtime 注入、HTTP session store 和 `.pi/research-agent/server.json`
配置已删除。

创建新会话或继续项目中的最新会话：

```bash
./research-agent --workspace reaction-a
./research-agent --workspace reaction-a -c
```

Host 身份位于 `<install>/var/state/host/server-id`；非输入 RPC 回执、内部生产者身份、
Monitor 健康状态和规范 Pi SQLite durable session repository 也位于同一目录。每个会话存储在 `var/state/pi/sessions/<workspace-id>/<session-id>/`，目录中有 `meta.json` 和 `session.sqlite`；元数据保存 `workspace_id`、`session_id` 和 `cwd`，因此 agent loop 继续在 workspace 目录执行。Native Pi
Harness 不接受 workspace `.pi/sessions`。
工作区必须是配置的 workspace root 下、经过验证的直接子目录。

默认终端通过 Host 返回的本地 descriptor 使用 Pi 官方 native remote client，不需要 tmux 或
PTY scraping。Host 重启会保留 SQLite durable transcript、operation/queue ID、回执和 Monitor outbox；
重新连接的客户端从新的 Host epoch/cursor 恢复。

TS Phone 通过 ResearchAgent Link 连接该 Host。安装时启用 Phone access，并提供 HTTPS ResearchAgent Link Relay
origin 和 Relay 管理员创建的一次性 Host enrollment code。交互式安装会在耗时的运行时安装
完成后、写入 Phone manifest 前才询问这个短期 code，避免安装超过 code 有效期；非交互式安装
仍通过 `--link-enrollment-code` 直接提供。安装器写入
`var/state/host/link.json` 及仅所有者可读的 `var/state/host/host.token`；Host
只向 Relay 建立出站 WSS，不会向 Relay 或互联网暴露 App Server 端口。

如果本机已经单独安装了 Relay，设置 `RESEARCH_AGENT_WITH_LINK_RELAY=false`，安装器会优先读取已知目录（包括
`/home/iaw/soft/research-agent-link`）及其 `research-agent-relay.service`，自动填充 Relay URL；也可以显式
指定 `--link-relay-root /path/to/research-agent-link`。Relay 仍然是独立服务；统一安装器在明确启用
Relay 时负责其生命周期，Host 安装器只负责兑换 enrollment code。

统一安装器会在 `<install>/etc/link-relay.json` 写入所有权标记。卸载时默认停止并移除该
安装创建的 Relay 服务和代码，但保留 Relay 数据库；使用 `--purge-relay-state` 或
`--purge-all` 才会删除 enrollment 和设备状态。没有该标记的共享 Relay 不会被主安装卸载。

Host 上线后使用以下命令管理 Phone 授权：

```bash
./research-agent phone pair
./research-agent phone devices
./research-agent phone revoke <device-id>
```

内网客户端可以使用 SSH transport 连接远端 Host。远端安装必须包含
`apps/agent/transport/ssh.mjs`，客户端通过 SSH 为 Host 和 Pi socket 启动该 proxy，
不监听公网 TCP 端口。SSH host key 校验由 OpenSSH 完成，Host 仍执行 `research-agent-host/2` protocol
协商。可用重复的 `--ssh-option` 传入 `-i` 等 OpenSSH 选项。

安装器可以持久化该配置，之后直接运行 `research-agent --workspace`：

```bash
./scripts/install_wizard.py --non-interactive --yes \
  --install-root /home/iaw/research-agent \
  --remote-host pi.example \
  --remote-host-socket /run/user/1000/research-agent/host.sock \
  --remote-proxy-path /opt/research-agent/apps/agent/transport/ssh.mjs \
  --ssh-config /home/user/.ssh/config \
  --ssh-option=-i --ssh-option=/home/user/.ssh/id_ed25519
```

配置会写入 owner-only 的 `etc/remote-host.json`；命令行显式参数只覆盖当前一次启动。

`phone pair` 输出已配置的 Relay URL 和八位配对码。配对码五分钟后失效且只能使用一次；TS
Phone 将其兑换为平台安全存储中的可撤销设备凭据。Phone 凭据、Host token 和 TS Web HTTP
token 相互独立。Phone 是普通的交互式 Pi 客户端，与终端共享同一 Harness lane 和工具；TS Web
仅是只读客户端。

## Monitor 运维

Host 为 workspace root 启动一个 Monitor worker，轮询持久化 Compute 状态，并在每个
workspace 内写入 registration、event 和 delivery 回执。`monitor/list`、`monitor/status`、
`monitor/enable`、`monitor/disable` 提供健康状态和积压信息。next_run 持久保留认证执行事件，原会话忙或自动执行暂停时继续等待。投递与消费身份独立于 Memory revision，输入接受不代表完成科学解释。Agent 读取关联 Node 与 Job 回执，再记录结论。

规范的 `workspace_manifest.json` identity 会先被验证，再由 Monitor 用于 Host 路由。其
`workspace_id` 在 Research Memory、本地运行记录和远程计算 intent 中保持一致；不存在独立的
`workspace.json` 身份或 alias 层。

## 会话历史

Native Pi Harness 只接受安装级 `var/state/pi/sessions/` 下的 SQLite durable session。
旧 workspace 历史文件不会导入或恢复；研究连续性应保存在 Research Memory，而不是第二套
session 格式。

## 工作区初始化

首次运行 `./research-agent --workspace <name>` 时，客户端会在配置的 workspace root 下创建 0700 工作区
以及 `research_workspace/2` 的 `workspace_manifest.json` 与 Research Memory 存储。Node 按需在 `research/nodes/` 创建，不生成全局 progress 或 lifecycle 文档。Host 的 WorkspaceDirectory 也提供同一操作给 TS Phone。Host 不会创建无名项目；
初始化会验证规范协议，遇到旧格式或不完整状态时拒绝而不是重写。

## 运行 TS Web Research Explorer

安装时选择 TS Web 后，可使用只读浏览器：

```bash
./TSWeb serve \
  --state-dir var/state/web \
  --auth-token-file "$HOME/.local/share/research-agent/etc/web/auth.token" \
  --source-root /configured/workspace-root/reaction-a \
  --label "Reaction A" --host 127.0.0.1 --port 8766
```

只有在使用认证 token 文件时，才允许安装配置 `--web-host 0.0.0.0 --allow-remote`；直接运行
TS Web 时对应 `serve --host 0.0.0.0 --allow-remote`。安装器会拒绝缺少这两个显式设置的
非回环绑定。TS Web 只读，既不拥有 Pi session，也不提供科学写入路由。
其 bearer token 与 ResearchAgent Link Host 和 Phone 设备凭据分开。

token 文件不存在时，安装器会生成随机 TS Web token。也可以传入 8--100 个 URL-safe 字符的
`--web-auth-token`，或在交互隐藏提示中输入。命令行 token 可能出现在 shell history 或进程
列表中，生产环境应预先创建 `0600` token 文件并使用 `--web-auth-token-file`。

## 模型配置

模型目录和 API adapter 由固定 Pi release 提供。安装时，安装器会把 Host 服务账户
`~/.pi/agent/` 中已有且安装目录缺失的 `models.json` 与 `auth.json` 复制到私有安装状态
`<install>/etc/pi/`；升级不会覆盖安装目录中已有的文件。如果没有可导入的配置，必须先
通过 Pi 或 provider 环境变量配置凭据，再创建 ResearchAgent 会话。终端、TS Phone 和其他客户端连接
同一 session，因此共享模型和工具集合；模型兼容性见
[模型兼容性](MODEL_COMPATIBILITY.zh-CN.md)。

## 升级、回滚和恢复

再次运行 `./install.sh` 并选择相同安装根目录。安装器下载或构建新的 content-addressed release，
验证 package inventory，再原子切换 `current`。保留模型配置和凭据。本版本只接受当前工作区与
会话协议；替换不兼容版本时使用全新工作区和会话，安装器不导入或转换旧研究状态及 Web 登记。

安装器串行执行升级，在切换版本前停止受管 Host/Web 写入进程。独立托管的计算服务继续运行。
配置及环境检查先于服务启动；启动后核验 Host 的实际版本和 Web 的 State 通道。
同一安装的更新必须保留原有 service scope。

服务启动前捕获失败，可恢复之前的程序和配置快照。服务开始接收新任务后，失败会保留选定版本
并停止服务，通过再次运行安装器继续修复。安装进程意外终止后也继续修复，因为原配置快照已不可用。
`var/state/installation/maintenance.json` 持久记录这一边界，其中不包含凭据。未完成维护期间阻止普通
启动；这是对当前版本写入的保护，不承担历史数据迁移。

以下恢复只针对当前协议下创建的任务与会话。
如果 Host 退出，重启唯一的 Host service。进程退出会释放 Root lock，Pi SQLite session 保持完整。
本地计算 worker 在可用时运行于独立的临时 user service，Host 重启通常不会中断；恢复后仍须检查
Job 状态。终端或 Phone 重连时首先接收新的 session snapshot；传输失败且结果不确定时，prompt
不会自动重发。

查看 `<install>/var/log/` 中最新的安装日志，并按安装时的 scope 检查服务：

```bash
systemctl --user status ts-app-server-research-agent.service  # user scope
systemctl status ts-app-server-research-agent.service         # system scope
```

## 卸载

运行 `./uninstall.sh`。默认保留配置的 workspace root、Pi session history、凭据和配置；删除安装
根目录必须显式确认。卸载器还会在配置的 scope 中停止并删除匹配的 App Server、TS Web 和
本安装创建的 Link Relay service。共享或没有所有权标记的 Relay 会保留。如果 Relay 目录曾被
手动删除，请使用它原来的 `--install-root` 调用独立 Relay 卸载器；即使代码路径不存在，也会
清理残留 unit。

## 科学计算绑定就绪检查

安装器分别记录 `configuration_validated`、`environment_verified`、
`execution_verified` 和 `not_verified`，同时保留具体检查范围、目标和配置摘要。
本次选中的目标验收失败会在发布前停止安装；未选择的远端保留未验证状态，旧结果不冒充
本次通过。底层逐执行入口的依赖版本与导入结果仍包含在详细报告中。

安装先准备候选版本、Python 环境、Pi 和验收 Job，再进入短暂维护窗口停止服务并发布。
准备失败不改变活动版本；服务启动后的失败使用原有维护恢复机制，不回滚研究数据。

`--purge-runtime` 只删除本安装拥有且没有未完成 Job 或活动进程引用的本地科研环境。
外部、远端及无归属记录的环境保留，并在卸载结果中列出。
准备失败时也会保留环境目录的所有权记录，供重试和清理。`--purge-all` 即使移除
安装目录，也会保留这些外部目录，并在结果中列出路径。

报告整理和邮件 check/prepare/send/status 通过原生 bash 执行；job_* 用于科学计算。邮件继续使用安装凭据和持久化投递回执。
