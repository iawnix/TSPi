# TSPi 化学机制框架图

[English](README.md) | 简体中文

文件：

- `tspi-mechanism-framework.svg`：可编辑的化学机制框架图。
- `tspi-mechanism-framework.pdf`：183 mm × 112 mm 的单页矢量导出。

`tspi-mechanism-framework.svg` 将 Kernel 拥有的科学状态与执行/证据平面分开。图中
强调 Root Agent 先提出 Claim、反证条件和停止规则，随后通过显式 ChangeSet 让 Kernel
创建 bounded Node 并记录来源；Skill/Plugin 只产生可检查产物，不直接产生科学结论。
NodeGate 控制 Node 是否可以 `completed` 关闭，ClaimGate 评估累积 Finding；Root 显式
记录 Claim 状态并选择后续 Node，ResearchMap 是客户端直接渲染的规范状态。
