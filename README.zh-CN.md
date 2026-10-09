# ResearchAgent

[English](README.md) | [简体中文](README.zh-CN.md)

ResearchAgent 是一个 AI 科研助手：帮助你制定研究方案、运行计算、分析结果，并整理成可追溯的研究报告。
目前主要提供计算化学技能，涵盖分子结构、过渡态搜索、反应路径分析和能量比较。
研究记录与计算结果保存在工作区中，可以随时继续研究。

## 可以做什么

- 根据研究问题选择方法、准备输入，在本机或配置好的远程计算平台运行任务。
- 分析结构、频率和反应路径，记录结论、依据与尚未解决的问题。
- 整理包含分子图、数据表和能量曲线的报告；具体内容取决于已有计算证据。
- 在终端中交互，通过 TS Phone 连接同一工作区，或用可选的 TS Web 浏览研究记录。

项目仍在积极开发。计算需要相应的科学软件及环境配置，详见[科学计算指南](docs/SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md)。

## 安装

准备 Git、Python 3.11+、Node.js 22.19+、Conda/Mamba 和模型访问凭据，然后运行：

```bash
git clone https://github.com/iawnix/TSPi.git
cd TSPi
./install.sh
```

需要非交互安装时，编辑 `install-configured.sh` 中的配置并执行：

```bash
./install-configured.sh
```

安装、模型配置、远程计算、手机连接和服务管理见[安装与运维](docs/INSTALLATION.zh-CN.md)。

## 开始研究

打开一个工作区：

```bash
./research-agent --workspace reaction-study
```

在终端中直接描述研究问题、已有材料和希望得到的结果。之后可以继续最近的会话：

```bash
./research-agent --workspace reaction-study -c
```

工作区服务由安装器配置。会话切换与终端操作见[终端文档](docs/TERMINAL.zh-CN.md)，
手机连接见 [ResearchAgent Link](docs/RESEARCH_AGENT_LINK.zh-CN.md)。

## 文档

- [文档索引](docs/README.zh-CN.md)
- [Skill 目录与加载语言](skills/README.zh-CN.md)
- [科学计算与远程执行](docs/SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md)
- [模型兼容性](docs/MODEL_COMPATIBILITY.zh-CN.md)
- [架构](docs/ARCHITECTURE.zh-CN.md)与[维护者指南](docs/MAINTAINER_GUIDE.zh-CN.md)

## 开发

在源码目录执行：

```bash
python3 tools/test/runner.py list
python3 tools/test/runner.py fast -- -q
npm run lint:public
npm run lint:skills
```

测试环境、缓存和证据统一放在本机私有的 `local_debug/`，不得提交或打包。
测试准备与完整检查见[维护者指南](docs/MAINTAINER_GUIDE.zh-CN.md)。

## 卸载

```bash
./uninstall.sh
```

卸载器会询问是否保留工作区、会话、配置和托管运行时。

## 社区与许可

- [贡献指南](CONTRIBUTING.zh-CN.md)
- [安全策略](SECURITY.zh-CN.md)
- [行为准则](CODE_OF_CONDUCT.zh-CN.md)
- [变更日志](CHANGELOG.zh-CN.md)

项目源码采用 [Apache License 2.0](LICENSE)。第三方依赖、Pi 源码、科学软件及随附资源可能适用各自的许可证。
