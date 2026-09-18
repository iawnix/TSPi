# TSPi 假设—证据循环重构规划

[English](PLAN_HYPOTHESIS_PROOF_LOOP.md) | 简体中文

本文件是英文规划的中文 companion，记录设计边界和实现里程碑；它不是当前运行状态
的验收报告。当前实现由一个安装级原生 Pi App Server Host 服务多个工作区，TS Phone
是独立的 Radius 客户端。

## 要解决的问题

TSPi 不应把“假设 -> 固定计算序列”写成中央路由器。Root Agent 根据科学问题提出
可验证的 Claim、方法和预算；Kernel 检查类型、引用、权限、状态和副作用；确定性
执行器记录产物；解析器产生候选观察；Root Agent 解释证据并选择继续、分支、回溯或停止。

```text
Root Agent 提出问题 -> ResearchNode -> 能力执行 -> 产物/候选观察
                  -> Root 核验 -> ProofSpec/Gate -> 下一项研究决定
```

## 三层职责

- Scientific Agent：拥有问题、假设、预测、反证条件、方法选择、解释和下一步策略。
- Research Kernel：拥有 ID、schema、引用、revision、事务、provenance、digest、验证
  和只读 projection；不拥有科学策略。
- Capability/Skill/Plugin：执行计算、解析、渲染、报告、远程控制和通知；不拥有规范
  科学状态。

固定协议 envelope 包含记录类型、ID、引用、类型表示、artifact 角色、能力和事务元数据；
科学概念、假设、解释和分支理由属于 Root Agent 的开放 payload。

## 假设—证据循环

1. 读取有界 frontier/delta，区分科学记录和运行记录。
2. 注册问题、假设、预测和反证条件。
3. 创建一个目标和交付物明确的 ResearchNode。
4. 提议带 schema 的 capability request，由 Kernel preflight。
5. 执行并写入 Attempt、Activity 和 artifact digest。
6. 解析为候选观察，不把原始输出直接视为证据。
7. Root 对照产物核验并通过 `ts_change` 提升 Observation 或 Finding。
8. 冻结 ProofSpec，产生绑定 revision 的验证结果或 GateResult。
9. 由 Root 记录 Claim 解释和下一个依赖 Node。

ProofSpec 是版本化、可证伪的证据标准，不是对化学机理的永久数学证明。NodeGate
只允许一个 bounded Node 收尾；ClaimGate 汇总证据辅助 Claim 解释，二者都不会自动
替 Root Agent 修改科学结论。

## Web、Phone 与发布

TS Web 只消费 Research Kernel projection；它可以展示轨迹、证据、Gate、Finding 和
运行详情，但不提供科学写入，也不推断下一步。TS Phone 连接同一 Pi session，不创建
第二个 broker 或工作流 runtime。发布顺序依次冻结合同、实现通用能力、完善观察和
验证、接入 Web/Phone projection，最后构建并安装经过 manifest 校验的 package。

## 风险控制

Kernel 拒绝 malformed value、过期引用、未知能力、危险 effect 和不安全路径；它不会
因为科学词汇陌生而拒绝 Claim。Capability registry、digest、replay、隔离 Compute
和 advisory Review 用来控制执行和证据风险，但不替代 Root Agent 的科学判断。
