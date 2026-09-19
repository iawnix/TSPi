---
name: tspi-method-selection
description: 为有边界的研究问题选择科学方法、已注册 Backend capability 以及命名的本地或远端计算环境。
---

# TSPi 方法选择

[English version](SKILL.md)

在方法、Backend、capability 或计算环境尚未确定时，先使用本 Skill。方法选择属于科学
决策；本 Skill 不启动计算。

从区分相关 Claim 所需的 Finding 出发，考虑体系大小、电荷、自旋、电子态、金属或多参考
风险、溶剂、约束、目标可观测量、预期误差、候选质量与成本。查询实时 capability 和环境
目录，不要根据 Skill 描述推断软件可用。选择一个命名的本地或远端环境，并确认其 Backend
绑定支持准确的 capability 与参数。

只有低成本探索能回答已声明问题时才使用它。明确何时需要更高层级计算、替代方法或稳健性
检查，并把选择与理由保存在 Node 和不可变 calculation intent 中。

## 参考资料

- [method_selection.md](references/method_selection.md)：科学判据。
- [backend_contract.md](references/backend_contract.md)：Backend 与 capability 边界。
- [compute_environments.md](references/compute_environments.md)：命名的本地/远端环境及远端
  Platform 细节。
- [runtime_environment.md](references/runtime_environment.md)：安装级科学运行时诊断。
