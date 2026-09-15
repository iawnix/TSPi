# TSPi

[English](README.md) | [简体中文](README.zh-CN.md)

TSPi 是基于 Pi 的计算化学研究助手，面向过渡态搜索和反应路径分析。研究状态、
证据、计算结果和报告都保存在同一个工作区。

## 安装

准备 Git、OpenSSH、Python 3.11+、Node.js 22.19+、Conda/Mamba 以及 Pi 凭据，
然后运行交互式安装器：

```bash
git clone git@github.com:iawnix/TSPi.git
cd TSPi
./install.sh
```

核心安装始终包含 Agent、科学运行时和分子渲染；TS Web 是可选组件。安装器可以
配置每个工作区的 App Server systemd 模板；不再安装 TS Phone 守护进程。

详见[安装与运维](docs/INSTALLATION.md)，其中包含依赖、运行时、升级、回滚和恢复说明。

## App Server 与终端

每个工作区运行一个 Pi App Server，由它独占会话、对话历史、模型状态和 Root 锁：

```bash
./TSPi --app-server --workspace reaction-a
```

普通 TSPi 命令是该 App Server 的本地终端客户端：

```bash
./TSPi --workspace reaction-a
```

TS Phone Flutter 应用通过 Pi Radius 连接同一个 App Server，不再存在第二套 Host 或
broker。参阅[终端文档](docs/TERMINAL.zh-CN.md)、[中文架构](docs/ARCHITECTURE.zh-CN.md)、
[TS Phone 客户端说明](https://github.com/iawnix/ts-phone/blob/main/README.zh-CN.md)。

## 研究与远程计算

在 `.pi/remote.toml` 配置 SSH/Torque 和软件 profile，然后验证：

```bash
./TSPi --check-remote
```

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
python3 -m unittest discover -s tests -p 'test_*.py'
npm run lint:public
```

[维护者指南](docs/MAINTAINER_GUIDE.md)介绍包校验、App Server 生命周期和发布流程；
英文版本见 [Architecture](docs/ARCHITECTURE.md)、[Terminal](docs/TERMINAL.md)。
