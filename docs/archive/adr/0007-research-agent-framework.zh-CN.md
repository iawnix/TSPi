# ADR 0007：Research Agent Framework 边界

> Historical archive / 历史归档：本文记录旧设计或一次性验证，不是当前接口合同，也不代表本次重构已通过验收。当前设计见 [Research Memory plan](../../RESEARCH_MEMORY_DESIGN_AND_IMPLEMENTATION_PLAN.zh-CN.md)。

状态：已被 [ADR 0010](0010-retire-parallel-runtimes.zh-CN.md) 取代。

本历史设计采用的平行框架或 capability 调度路径已退出当前实现，其代码及孤立测试已删除。
现行边界见 [ARCHITECTURE.zh-CN.md](../../ARCHITECTURE.zh-CN.md) 与
[执行边界](../../ARCHITECTURE_BOUNDARIES.md)。

当前使用 Native Host/Pi Harness、Research State、Job Runtime 和已安装 Skill。
`artifact_derive` 只记录描述，不执行 provider。原始决策和实现保留在 Git 历史中。
