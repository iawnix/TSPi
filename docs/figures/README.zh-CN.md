# TSPi 研究架构图

[English](README.md) | 简体中文

文件：

- `tspi-research-architecture.svg`：可编辑矢量图。
- `tspi-research-architecture.pdf`：183 mm × 109.8 mm 的单页横向矢量导出。
- `tspi-research-architecture.tif`：600 dpi、4326 × 2592 像素的位图导出。
- `tspi-research-architecture.drawio`：可在 diagrams.net 中继续编辑的源文件。
- `tspi-mechanism-framework.svg/.pdf`：面向化学机制的框架图。

建议图注：Root Agent 提出科学问题、假设、方法和显式决定；确定性的 Research
Kernel 是 Phase–Node–Claim 图、provenance ledger 和声明式验证记录的唯一变更
权威。能力 adapter 生成可检查的 artifact 和 parser candidate；只有 Root 核验后的
证据才能提升为不可变 Observation，并由冻结的 ProofSpec 评估。验证结果、开放
Finding 和回溯决定进入下一步研究。TS Web 直接渲染 canonical ResearchMap 的有界视图，终端与 TS Phone
连接共享 Pi session；它们都不是第二套科学状态存储。

图使用色盲友好的语义色：teal 表示规范状态，navy 表示数据流，amber 表示能力，
violet 表示 provenance，coral 表示验证和决定反馈，blue 表示证据面。打开 `.drawio`
文件即可在 [diagrams.net](https://app.diagrams.net/) 中调整版式并重新导出。

## 化学机制框架

`tspi-mechanism-framework.svg` 将 Kernel 拥有的科学状态与执行/证据平面分开。图中
强调 Root Agent 先提出 Claim、反证条件和停止规则，随后由 Kernel 创建 bounded Node
并记录来源；Skill/Plugin 只产生可检查产物，不直接产生科学结论。NodeGate 关闭单项
研究任务，ClaimGate 评估累积证据，Research Map 以只读方式展示历史轨迹。
