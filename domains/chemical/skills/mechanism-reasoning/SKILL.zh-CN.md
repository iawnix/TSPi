---
name: mechanism-reasoning
description: 使用明确的物种身份、原子映射、基元步骤、替代假设与可证伪条件形成、比较并修订反应机理假设。
---

# CoRAgent 反应机理思考

[English version](SKILL.md)

使用本 Skill 定义和质疑反应机理假设、识别基元步骤与竞争路径，或判断哪种观察能够区分
替代解释。本 Skill 基于检查过的原始输出及明确引用的研究结果推理，不能替代过渡态验证、IRC 或能量学。

显式定义物种、组成、电荷、自旋或电子态、原子映射、成键变化、环境与可逆性。在 Node 的 proposal 中写明机理假设，在 plan 中描述预测与可证伪观察；结果中的支持或冲突用 conclusion 和证据说明。需要独立比较的方案可用 alternative_to 关联。研究依赖不表示化学连通性。

在研究笔记中明确检查标准、支持证据、未解决问题和下一步，引用实际收集的材料。计算完成不能代替对科学结论的判断。

将物种身份、基元步骤连通性、鞍点证据、能量学、动力学与稳健性拆成可以独立失败的问题。
保留竞争机理与意外结果。证据挑战当前问题框架时，修订当前 Node 的思路；独立新问题才创建相关 Node，不改写既有结果。

## 参考资料

- 物种、映射与输入准备见
  [reaction_mapping.zh-CN.md](../chemical-input/references/reaction_mapping.zh-CN.md) 和
  [molecular_preparation.zh-CN.md](references/molecular_preparation.zh-CN.md)。
- 路径假设与化学连通性见 [pathway_model.zh-CN.md](references/pathway_model.zh-CN.md)。
- 可区分假设与 falsifier 见
  [mechanism_reflection.zh-CN.md](references/mechanism_reflection.zh-CN.md)。
- 重复或意外结果后的重新框定见
  [strategy_reflection.zh-CN.md](references/strategy_reflection.zh-CN.md)。
