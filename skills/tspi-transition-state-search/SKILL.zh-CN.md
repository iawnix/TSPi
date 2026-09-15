---
name: tspi-transition-state-search
description: 选择和评估 QST、扫描、NEB、构象搜索、分支与恢复等过渡态候选生成方法。
---

# TSPi 过渡态搜索

[English version](SKILL.md)

当问题是如何构造、探索或恢复过渡态候选时使用本 Skill。工作区和证据合同
使用 `tspi-orchestration`。生成候选结构后，继续开展确认所提过渡态所需的计算和验证。

## 方法选择

根据基元步骤假设、端点质量、原子映射、电子态、构象不确定性、体系大小、
成本和可用执行器选择方法。QST/QST2/QST3、直接过渡态优化、弛豫扫描、NEB、
片段构造和构象采样解决的是不同的候选生成问题。根据当前假设和证据选择方法及
执行顺序，通过能力目录查询可用操作。

## 搜索流程

每个候选生成问题使用一个 ResearchNode，并用逻辑 artifact ID 绑定输入。记录
方法、假设、参数和预期区分结果。保留失败候选和方法变化；假设或交付物改变时
启动依赖 Node。候选仍需根据 Claim 补充驻点、振动模式、连通性、电子态和稳健性
证据。

## 参考资料

- 候选构造和后续证据：[candidate_generation.md](references/candidate_generation.md)
- 后端选择：[backend_selection.md](references/backend_selection.md)
- ASE NEB 执行器：[ase_neb_executor.zh-CN.md](references/ase_neb_executor.zh-CN.md)
- ASE NEB 执行器（英文）：[ase_neb_executor.md](references/ase_neb_executor.md)
- 机理 Claim 反思：[mechanism_reflection.md](references/mechanism_reflection.md)
- 重复结果和失败搜索反思：[strategy_reflection.md](references/strategy_reflection.md)
