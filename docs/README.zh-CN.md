# TSPi 文档

[English](README.md) | [简体中文](README.zh-CN.md)

按问题选择最小的规范文档。根目录 [README](../README.zh-CN.md) 是安装总览；以下文档描述
运行时和研究合同。

| 需求 | 文档 |
| --- | --- |
| 安装、配置、升级、恢复 | [安装与运维](INSTALLATION.zh-CN.md) |
| 理解 Agent、Kernel、Host、Monitor、Memory 和 Compute 边界 | [架构](ARCHITECTURE.zh-CN.md) |
| 理解 ResearchMap 对象与 turn checkpoint | [ResearchMap 设计](RESEARCH_MAP_DESIGN.zh-CN.md) 与 [ADR 0006](adr/0006-unified-research-harness-lifecycle.zh-CN.md) |
| 选择并运行已注册科学能力 | [Capability 与计算模型](CAPABILITY_COMPUTE_MODEL.zh-CN.md) 与 [科学能力运维](SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md) |
| 使用终端、Phone、浏览器或 Monitor | [终端](TERMINAL.zh-CN.md)、[TSPi Link](TSPi_LINK.zh-CN.md) |
| 维护、测试、打包和发布 | [维护者指南](MAINTAINER_GUIDE.zh-CN.md) 与 [参与开发](../CONTRIBUTING.zh-CN.md) |
| 理解模型/provider 支持边界 | [模型兼容性](MODEL_COMPATIBILITY.zh-CN.md) |
| 查看历史设计决策 | [架构决策记录](adr/) |

## 权威性与状态

代码和版本化 schema 是行为权威。文档说明公开 contract，代码变化时必须同步更新。历史
ADR 不构成当前兼容性承诺；当前 Native-only 运行时和最新已接受 ADR 定义受支持行为。

本仓库当前没有许可证授权。在仓库所有者添加并确认许可证前，不要重新分发或复用源码。
