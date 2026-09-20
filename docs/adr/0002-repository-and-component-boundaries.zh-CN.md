# ADR 0002：仓库与组件边界

[English](0002-repository-and-component-boundaries.md) | 简体中文

- 状态：已接受并已实现主要边界

## 决定

TSPi 是核心产品和必需仓库，拥有 Root Agent 集成、Research Kernel、规范工作区、
确定性计算/产物/报告/远程/通知机制、TS Web ResearchMap provider、Pi extensions、
组件兼容性和安装器。

`ts-phone` 是独立的可选客户端仓库，拥有移动应用、部署、签名和发布产物；它不提供
session broker，也不重新定义 Pi wire protocol。`components/ts-web/` 是可选组件，拥有
浏览器 UI、HTTP transport、workspace catalog client 和静态资源；它只能消费公开版本化
ResearchMap，不得导入 TSPi 私有 Python 模块或直接读取工作区物理路径。

```text
TSPi 核心仓库       -> kernel、Root runtime、ResearchMap provider、suite installer
ts-phone 独立仓库   -> 移动客户端和发布工具
components/ts-web/  -> 浏览器 ResearchMap client 和 HTTP/UI
```

## 协议与发布

Pi 拥有 App Server 和 Chord 协议；TSPi 拥有 Link 的注册、授权和字节转发协议；
TS Phone 是连接原生 Pi session 的展示适配器。TSPi 拥有 TS Web 使用的 ResearchMap
合同。每个可选组件通过
显式 descriptor 绑定版本、协议、能力、入口和 artifact digest；能力描述不能授予科学
变更权。省略 Web descriptor 表示组件不可用，不应从源码路径静默嵌入。

Web transport 使用 `research-map-provider/1`，其中 `/map` 返回 workspace metadata 加上
直接的 `research-map/1` 规范序列化。catalog、collection 和 object-detail route 只是同一
map 上的传输便利接口，不构造另一套 view 或 graph 模型，也不暴露物理工作区路径或
变更入口。

发布清单是 payload 的单一来源，包检查和安装器必须验证同一清单。开发测试和生成文件
不应进入生产归档。当前目录布局将 Kernel 放在 `packages/ts-agent-kernel/`，
TypeScript runtime 放在 `packages/ts-agent-runtime/`，原生 App Server 放在 `apps/`。

## Review 边界

`packages/ts-agent-runtime/agents/review/` 实现隔离的 advisory runtime。公开请求可通过
`reviewerRole` 选择角色；当前包提供版本化的 `general` descriptor。runtime 为该角色
构造类型化 task packet，并记录 prompt revision、继承模型策略、artifact budget 和
advisory authority。

确定性 aggregator 会保留每份 reviewer 结果、分类失败和冲突观点，而不会把分歧隐藏成
共识；这些行为已有测试。当前公开执行仍是一次有界 Review 请求，不是并行 reviewer
编排。Root 必须明确处置建议，reviewer 不能直接改变规范科学状态。增加角色或并行编排
属于后续独立变更，也不能暗示存在第二套 model provider。

## 后果

组件可以独立测试和发布，客户端不会形成第二套科学状态。代价是 manifest、协议版本、
archive digest 和跨组件 CI 需要明确协调；这比共享私有导入或隐式 broker 更可审计。
