# TSPi

[English](README.md) | [简体中文](README.zh-CN.md)

TSPi 是基于 Pi 的计算化学研究助手，面向过渡态搜索和反应路径分析。研究状态、
证据、计算结果和报告都保存在同一个工作区。

## 安装

准备 Git、Python 3.11+、Node.js 22.19+、Conda/Mamba 以及 Pi 凭据。只有使用
私有 SSH 仓库或远程计算时才需要 OpenSSH。然后运行交互式安装器：

```bash
git clone https://github.com/iawnix/TSPi.git
cd TSPi
./install.sh
```

核心安装始终包含 Agent、科学运行时和分子渲染；TS Web 是可选组件。安装器配置
整个安装目录共用的 App Server Host；不再安装 TS Phone 守护进程。

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

## App Server 与终端

整个安装目录运行一个 Pi App Server Host，由它为所有工作区独占会话、对话历史、模型状态和 Root 锁：

```bash
systemctl --user start ts-app-server-tspi.service
```

使用 `systemctl --user stop|restart|status ts-app-server-tspi.service` 管理
Host 生命周期。`--host` 只是服务内部入口，不用于日常启动。

普通 TSPi 命令是该 App Server 的本地终端客户端：

```bash
./TSPi --workspace reaction-a
```

TS Phone Flutter 应用通过 Pi Radius 连接同一个 App Server，不再存在第二套 Host 或
broker。参阅[终端文档](docs/TERMINAL.zh-CN.md)、[中文架构](docs/ARCHITECTURE.zh-CN.md)、
[TS Phone 客户端说明](https://github.com/iawnix/ts-phone/blob/main/README.zh-CN.md)。

## 研究与远程计算

安装时可以在统一的 `.pi/compute.toml` 中配置 Backend 与 Compute environment（使用
`--compute-config` 导入已有文件）。本地与远端 environment 都位于这一个文件中。
远端 environment 可用下面的命令验证：

```bash
./TSPi --check-remote
```

`ts_calc` 是 local 和 remote 共用的唯一计算生命周期入口。每个 Compute
environment 都有 `kind = "local"` 或 `"remote"` 以及对应的 `backends` 表；只有
remote environment 额外包含 SSH/Torque 字段。`/compute` 和 `ts_environment` 工具
查询完整的 local/remote environment；远端就绪性检查属于已绑定计算的 preflight，
不再单独形成一套 remote 命令。

Skill 覆盖 Gaussian、xTB、CREST、ASE-NEB、结构验证、渲染、报告和邮件投递。详见
[Skill 目录](skills/README.zh-CN.md) 与 [术语表](skills/tspi-orchestration/references/glossary.zh-CN.md)。

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
```

[维护者指南](docs/MAINTAINER_GUIDE.zh-CN.md)介绍包校验、App Server 生命周期和发布流程；
英文版本见 [Architecture](docs/ARCHITECTURE.md)、[Terminal](docs/TERMINAL.md) 和
[Maintainer Guide](docs/MAINTAINER_GUIDE.md)。
