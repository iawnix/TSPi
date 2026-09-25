---
name: tspi-chemical-input
description: 在确定性 TSPi 分析或计算前，把自然语言化学名称和反应输入编译为经过核验的结构候选。
---

# TSPi 化学输入

[English version](SKILL.md)

当用户提供化学名称、名称与 SMILES 混合的反应式，或结构描述而不是已注册
的结构 artifact 时使用本 Skill。本 Skill 规定输入编译流程，不替代确定性
名称解析器、结构种子生成器、反应映射或过渡态验证。

## 流程

1. 保留用户原文，将每个反应物和产物标记为名称、SMILES、XYZ/artifact 或
   未解析描述。反应物和产物使用同一规则。
2. 对名称通过 `analysis.run` 调用 `chemical.name.resolve@1`，保留解析器
   provenance、候选、诊断和状态。
3. 把 `draft` 候选（包括 LLM 提出的 SMILES）、未解析名称、多个候选和未指定
   立体中心记录为输入问题，提出聚焦的澄清问题或请求 SMILES/结构 artifact。
4. 只有候选被明确确认或由确定性解析器唯一解析后，才能传给 `artifact.seed`。
   seed 只是初始几何，不是驻点，也不能证明连接关系。
5. 用确认后的物种执行 `reaction.parse`，检查守恒、映射候选和键变化；必须显式
   选择 atom mapping，不能把唯一图编辑当作机理证明。
6. 将原始名称、选定候选、解析器 provenance 和用户确认一起保存，保证可重放和审计。

## 信任状态

- `draft`：模型提出或未经身份核实的候选。
- `resolved`：确定性解析器得到且通过结构检查的唯一候选。
- `ambiguous`：多个候选或立体化学身份不完整。
- `confirmed`：用户或明确科学规则选定的候选。
- `unresolved`：没有注册解析器或没有有效候选。

不要把 `draft`、`ambiguous` 或 `unresolved` 结构提交给 Gaussian、TS 或 IRC。
名称解析成功后仍需进行反应守恒、mapping、电荷、自旋和 3D 验证，才能形成机理结论。

## 参考

- [name_resolution.zh-CN.md](references/name_resolution.zh-CN.md)：解析器合同、候选状态和失败处理。
- [structure_input.zh-CN.md](references/structure_input.zh-CN.md)：从确认分子图到 seed 和反应分析。
