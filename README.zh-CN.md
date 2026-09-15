# TSPi

[English](README.md) | [简体中文](README.zh-CN.md)

TSPi 是基于 Pi 的计算化学研究助手，面向过渡态搜索和反应路径分析。
你可以用自然语言描述研究问题，让它协助准备计算、提交远端任务、分析结果，
并把研究过程、验证依据和报告保存在同一个工作区中。

## 功能

- 从 SMILES 生成初始分子结构，或导入已有的 XYZ、Gaussian 输入文件。
- 使用 Gaussian、xTB、CREST 等工具开展结构优化、频率分析、构象搜索和反应路径研究。
- 通过 SSH 和 Torque 提交远端计算、查询进度、取回并解析结果。
- 记录假设、计算尝试、失败原因和验证结果，方便继续研究、比较方案和追溯结论。
- 渲染分子结构、反应路径动画、能量曲线和扫描曲线，生成研究报告。
- 通过终端和手机继续研究，在浏览器中查看进展与结果。

## 安装

在 Linux 主机上准备 Git、OpenSSH、Python 3.11+、Node.js 22.19+、Conda 或 Mamba，
以及已配置模型和凭据的 Pi。完整依赖见[安装文档](docs/INSTALLATION.md#prerequisites)。

运行安装向导：

```bash
curl -fsSL https://raw.githubusercontent.com/iawnix/TSPi/main/install.sh | bash
```

在向导中选择安装目录、Conda 路径、TS Web 和 TS Phone 组件，以及 systemd 服务。
选择 TS Phone 后，安装器会从 GitHub 下载源码、构建服务，并配置手机与终端共享会话。
TSPi 和 TS Phone 都可以选择分支、标签或提交，默认使用 `main`。
分子可视化依赖可通过安装参数 `--with-render` 加入。

非交互安装、服务配置和升级方式见[安装与运维](docs/INSTALLATION.md)。

## 开始研究

安装 TS Phone 并启动其服务后，进入安装目录打开共享终端：

```bash
cd /path/to/TSPi-installation
./TSPi --workspace reaction-a
```

直接运行 Pi 会话时，使用 `./TSPi --standalone --workspace reaction-a`。
服务启动和手机连接方式见下文。

实验性的原生 Pi App Server 使用独立 session store，并允许 Pi TUI 从另一终端连接。
准备固定版本的 Pi source checkout 后运行：

```bash
export TSPI_PI_SOURCE=/path/to/prepared/pi
./TSPi --app-server --workspace reaction-a --allow-writes
./TSPi --app-client --connect unix:///path/printed/by/server
```

省略 `--allow-writes` 时只开放只读工具。源码准备和生命周期细节见
[App Server 安装说明](docs/INSTALLATION.md#native-pi-app-server-experimental)。

每个研究项目保存在安装目录的 `workspaces/` 下。你可以先导入已有输入，
再提出具体的研究目标，例如：

> 请检查这份 Gaussian 输入，设计过渡态优化、频率和 IRC 验证方案。
> 计算完成后，整理结构、能量及反应路径连通性的依据，并生成报告。

远端计算前，在安装目录的 `.pi/remote.toml` 中配置 SSH 主机、队列、资源和计算软件，
然后检查连接：

```bash
./TSPi --check-remote
```

配置示例见[远端计算设置](docs/INSTALLATION.md#configure-remote-execution)。
结果收集步骤会把指定输出文件下载到工作区，随后在本地解析。

## 手机与共享会话

[TS Phone](https://github.com/iawnix/ts-phone) 提供 Android 客户端。
连接服务后，可以在手机上查看会话、发送消息和继续研究；终端也可以接入同一会话。

安装器在 TSPi 主机上部署 Phone 服务。手机上的 Android 客户端从匹配的
[TS Phone GitHub Release](https://github.com/iawnix/ts-phone/releases)下载并安装；
[产物说明](https://github.com/iawnix/ts-phone/blob/main/docs/artifacts.md)包含 ABI 和摘要信息。

如果安装时配置了 systemd 用户服务，启动服务后打开终端：

```bash
systemctl --user start ts-phone-tspi.service
cd /path/to/TSPi-installation
./TSPi --workspace reaction-a
```

再次连接最近的会话：

```bash
./TSPi --workspace reaction-a --continue
```

退出共享终端后，服务中的研究会话仍可继续运行。手机连接设置见
[Phone 配置](docs/INSTALLATION.md#configure-ts-phone)，会话切换和快捷键见
[终端使用说明](docs/TERMINAL.zh-CN.md)。

## 浏览器查看

TS Web 用于浏览研究路线、计算记录、科学结论、验证结果和文件。
可以在研究地图中查看分支与依赖，打开具体节点查看计算详情。

安装时选择 TS Web 后，可以手动启动：

```bash
/path/to/TSPi-installation/TSWeb serve \
  --state-dir /path/to/TSPi-installation/.pi/ts-web \
  --source-root /path/to/TSPi-installation/workspaces/reaction-a \
  --label "Reaction A" \
  --host 127.0.0.1 \
  --port 8766
```

在主机浏览器中打开 [http://127.0.0.1:8766/](http://127.0.0.1:8766/)。
多工作区和远程访问设置见[浏览器服务配置](docs/INSTALLATION.md#run-the-research-explorer)。

## 卸载

安装目录中附带卸载脚本：

```bash
/path/to/TSPi-installation/uninstall.sh --install-root /path/to/TSPi-installation
```

按提示选择是否清理工作区、会话、配置和运行环境。默认保留研究数据和凭据。
各项清理选项见[卸载说明](docs/INSTALLATION.md#uninstall)。

## 文档

- [安装与运维（英文）](docs/INSTALLATION.md)：依赖、配置、服务、升级与卸载。
- [终端使用说明](docs/TERMINAL.zh-CN.md)：项目、会话、快捷键和恢复。
- [Skill 目录](skills/README.zh-CN.md)：过渡态搜索、计算方法、结构验证、绘图和报告。
- [中英术语表](skills/tspi-orchestration/references/glossary.zh-CN.md)：研究记录中的常用术语。
- [中文架构](docs/ARCHITECTURE.zh-CN.md) / [Architecture](docs/ARCHITECTURE.md)：系统设计和数据模型。
- [开发维护指南（英文）](docs/MAINTAINER_GUIDE.md)：源码结构、测试和发布。

## 开发

在源码仓库中安装 Node 依赖并运行检查；Python 测试需要科学计算环境：

```bash
npm ci
npm run typecheck
npm run test:fast
npm run test:package
npm run test:terminal
npm run lint:public
```

完整测试和环境准备见[开发环境配置](docs/MAINTAINER_GUIDE.md#development-setup)
与[测试说明](docs/MAINTAINER_GUIDE.md#validation-tiers)。
