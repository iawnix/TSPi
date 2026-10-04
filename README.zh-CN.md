# TSPi

[English](README.md) | [简体中文](README.zh-CN.md)

TSPi 是基于 Pi 的、领域无关的科学 Research Harness，用于运行有边界的研究流程。
当前随附的 Skill 主要面向计算化学，包括过渡态搜索和反应路径分析。研究状态、证据、
计算结果和报告都保存在同一个工作区。

本仓库目前处于积极开发的预发布阶段。受支持的运行时只有 Native Pi Harness；已经退役的
ordinary-Pi 兼容运行时不会被打包或选择。当前化学 Skill 包只是领域无关的 Claim、Node、
Finding、Gate、Attempt 和 Artifact 模型的一个应用。

## 安装

准备 Git、Python 3.11+、Node.js 22.19+、Conda/Mamba 以及 Pi 凭据。只有使用
私有 SSH 仓库或远程计算时才需要 OpenSSH。然后运行交互式安装器：

```bash
git clone https://github.com/iawnix/TSPi.git
cd TSPi
./install.sh
```

需要非交互、可复现安装时，可以编辑 `install-configured.sh` 顶部的配置变量，或使用对应的
`TSPI_*` 环境变量覆盖，然后运行：

```bash
./install-configured.sh
```

需要固定源码版本时，将 `TSPI_INSTALL_REF` 设置为完整的 commit SHA。该脚本会把 compute、
name resolver、workspace、服务、Web、Phone 和通知配置统一传给同一个安装器。

同一次非交互安装默认会部署 Link Relay：默认 URL 是
`https://tsphone.iawnix.xyz`，安装器会创建 Relay 服务、生成一次性 Host enrollment
code，并自动完成 Host 注册。Relay 必须部署在另一台机器时，设置
`TSPI_WITH_LINK_RELAY=false` 并提供已有 code，或单独使用 `install-link-relay.sh`。

核心安装始终包含 Agent、科学运行时和分子渲染；TS Web 是可选组件。安装器配置
整个安装目录共用的 TSPi Host；不再安装 TS Phone 守护进程。

安装器还会询问是否安装可选的 TSPi 模型图标字体。交互安装默认安装；非交互安装
默认不写入用户字体目录，可显式传入 `--with-model-icons`，或用
`--without-model-icons` 禁用。字体安装在 `$XDG_DATA_HOME/fonts/tspi`（未设置时为
`$HOME/.local/share/fonts/tspi`），未安装时仍使用 Nerd Font/Unicode 回退；设置
`TSPI_ICON_STYLE=unicode` 或 `TSPI_ICON_STYLE=nerd` 可以覆盖自动选择。
模型字形使用补充私用区，不会被终端主 Nerd Font 中已有的图标码位遮蔽。
安装器会在可用时刷新 fontconfig 缓存；已经打开的终端可能需要重启后才能加载回退字体。

详见[安装与运维](docs/INSTALLATION.zh-CN.md)（英文版：[Installation and Operations](docs/INSTALLATION.md)），
其中包含依赖、运行时、升级、回滚和恢复说明；
模型与 provider 边界见[模型兼容性](docs/MODEL_COMPATIBILITY.zh-CN.md)。

完整文档导航见[文档索引](docs/README.zh-CN.md)。公开 Skill 入口和按需 references 见
[Skill 目录](skills/README.zh-CN.md)。

## Host 与终端

整个安装目录运行一个 TSPi Host，负责认证路由、幂等回执、会话发现和 Monitor 管理。
每个 workspace 由一个固定版本 Pi `SessionWorker`/`durable Harness` lane 拥有。lane
拥有 agent loop、模型、工具、transcript 和 Root lock；终端、Phone、Monitor 都是同一
lane 的客户端。直接打开工作区即可：

```bash
./ResearchAgent --workspace reaction-a
./ResearchAgent --workspace reaction-a -c
./ResearchAgent --workspace quick-task --mode light
./ResearchAgent --workspace reaction-study --mode research
```

Light 工作区只保留轻量的 memory 和生命周期状态，但与 Research 共用同一套计算入口：
`compute_catalog`、`compute_readiness`、`compute_run` 和 `compute_cancel`。Native 结果写入
`nodes/<execution_scope>/attempts/` 下的 operational execution scope 和 canonical workspace
Artifact 路径。Light 不创建 ResearchMap Claim/Node、可审计 Attempt、Monitor 状态或科学解释。需要这些生命周期保证时才使用
`--mode research`，例如过渡态/IRC 验证或比较机理结论。未注册的能力必须明确报告不可用，
不能用其它方法替代。

第一条命令创建 Harness 会话，第二条命令继续该工作区最近的可写会话。TSPi 先向 Host
取得本地 Pi connection descriptor，再启动 Pi 官方 native remote client/TUI。默认路径不
使用 tmux、PTY scraping，也不会创建第二个 agent loop。Host 不可用时会明确报错；旧的独立
Pi 运行时已经移除，Native Pi Harness 是唯一受支持的后端。
安装器默认创建、启用并启动 user-scoped Host；使用
`systemctl --user stop|restart|status ts-app-server-tspi.service` 管理 Host 生命周期。
Host 是终端、Phone 和 Monitor 的必需依赖；`--service-scope none` 仅用于底层包暂存或测试，
该模式下普通 workspace 入口不可用。`--host` 只是服务内部入口，不用于日常启动。

TS Phone Flutter 应用通过 TSPi Link 连接同一个 Host 和 Pi Harness lane。Phone 和 Host 分别向
TSPi Link Relay 建立出站 WSS；Relay 只负责设备授权与不透明字节转发，不管理会话或研究状态。
参阅 [TSPi Link](docs/TSPi_LINK.zh-CN.md)、[终端文档](docs/TERMINAL.zh-CN.md)、
[中文架构](docs/ARCHITECTURE.zh-CN.md)、
[TS Phone 客户端说明](https://github.com/iawnix/ts-phone/blob/main/README.zh-CN.md)。

## 研究与远程计算

安装时可以在统一的 `.pi/compute.toml` 中配置 Backend 与 Compute environment（使用
`--compute-config` 导入已有文件）。本地与远端 environment 都位于这一个文件中。
远端 environment 可用下面的命令验证：

```bash
./ResearchAgent --check-remote
```

`compute_run` 是 local 和 remote 共用的唯一计算生命周期入口。每个 Compute
environment 都有 `kind = "local"` 或 `"remote"` 以及对应的 `backends` 表；只有
remote environment 额外包含 SSH/Torque 字段。`/compute` 和 `compute_environment` 工具
查询完整的 local/remote environment；远端就绪性检查属于已绑定计算的 preflight，
不再单独形成一套 remote 命令。

Skill 覆盖 Gaussian、xTB、CREST、ASE-NEB、结构验证、渲染、报告和邮件投递。执行前必须
查询准确的版本化 capability 和计算环境；Skill 描述不能证明程序已经安装。详见
[Capability 与计算模型](docs/CAPABILITY_COMPUTE_MODEL.zh-CN.md) 和
[科学能力运维](docs/SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md)。

## 浏览器查看

TS Web 是可选的只读工作区浏览器。安装时选择后可使用 `TSWeb`；其 token 和状态保留
在安装目录的 `.pi/ts-web*` 中。

## 卸载

运行安装器附带的卸载脚本，并选择是否保留工作区、Pi 会话、配置和托管运行时：

```bash
./uninstall.sh
```

## 开发

在源码目录执行项目检查：

```bash
python3 tools/test/runner.py list
python3 tools/test/runner.py fast -- -q
python3 tools/test/runner.py source -- -q
npm run lint:public
npm run lint:skills
```

[维护者指南](docs/MAINTAINER_GUIDE.zh-CN.md)介绍包校验、App Server 生命周期和发布流程；
英文版本见 [Architecture](docs/ARCHITECTURE.md)、[Terminal](docs/TERMINAL.md) 和
[Maintainer Guide](docs/MAINTAINER_GUIDE.md)。

## 社区与项目政策

- [贡献指南](CONTRIBUTING.zh-CN.md) / [Contributing](CONTRIBUTING.md)
- [安全策略](SECURITY.zh-CN.md) / [Security policy](SECURITY.md)
- [行为准则](CODE_OF_CONDUCT.zh-CN.md) / [Code of Conduct](CODE_OF_CONDUCT.md)
- [变更日志](CHANGELOG.zh-CN.md) / [Changelog](CHANGELOG.md)

本仓库由项目拥有的源码采用 [Apache License 2.0](LICENSE) 授权。第三方依赖、固定版本的
Pi 源码、本地化学程序和随附资源可能适用各自的许可证；重新分发时必须保留相应声明。
