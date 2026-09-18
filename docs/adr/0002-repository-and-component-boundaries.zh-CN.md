# ADR 0002：仓库与组件边界

[English](0002-repository-and-component-boundaries.md) | 简体中文

- 状态：已接受并持续迁移

## 决定

TSPi 是核心产品和必需仓库，拥有 Root Agent 集成、Research Kernel、规范工作区、
确定性计算/产物/报告/远程/通知机制、TS Web projection provider、Pi extensions、
组件兼容性和安装器。

`ts-phone` 是独立的可选客户端仓库，拥有移动应用、部署、签名和发布产物；它不提供
session broker，也不重新定义 Pi wire protocol。`components/ts-web/` 是可选组件，拥有
浏览器 UI、HTTP transport、registry client 和静态资源；它只能消费公开版本化 projection，
不得导入 TSPi 私有 Python 模块或直接读取工作区物理路径。

```text
TSPi 核心仓库       -> kernel、Root runtime、projection provider、suite installer
ts-phone 独立仓库   -> 移动客户端和发布工具
components/ts-web/  -> 浏览器 projection client 和 HTTP/UI
```

## 协议与发布

Pi 拥有 App Server、Chord 和 Radius relay 协议；TS Phone 是连接原生 Pi session 的
展示适配器。TSPi 拥有 TS Web 使用的 workspace projection 合同。每个可选组件通过
显式 descriptor 绑定版本、协议、能力、入口和 artifact digest；能力描述不能授予科学
变更权。省略 Web descriptor 表示组件不可用，不应从源码路径静默嵌入。

发布清单是 payload 的单一来源，包检查和安装器必须验证同一清单。开发测试和生成文件
不应进入生产归档。当前 staged migration 将 Kernel 放在 `packages/ts-agent-kernel/`，
TypeScript runtime 放在 `packages/ts-agent-runtime/`，原生 App Server 放在 `apps/`。

## 后果

组件可以独立测试和发布，客户端不会形成第二套科学状态。代价是 manifest、协议版本、
archive digest 和跨组件 CI 需要明确协调；这比共享私有导入或隐式 broker 更可审计。
