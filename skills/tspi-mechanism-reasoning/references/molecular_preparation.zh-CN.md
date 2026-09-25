# 分子反应与结构 Capability

所有 capability 使用 version `1`。首次使用前查询其详细 schema；以下示例说明科学选择，
不规定固定顺序。

`reaction.parse` 接受 reaction SMILES 以及每个组分声明的一个多重度，或者显式的
`species`、`reactants` 与 `products`。例如：

```json
{
  "operation": "run", "nodeId": "node_1",
  "capability": "reaction.parse", "capabilityVersion": "1",
  "inputArtifacts": {},
  "parameters": {
    "reaction_smiles": "CCl.[OH-]>>CO.[Cl-]",
    "multiplicities": {"reactants": [1, 1], "products": [1, 1]}
  }
}
```

生成的 `ts-reaction-spec/1` 包含显式氢、同位素、形式电荷、声明自旋、图、identity 与
化学计量 occurrence，并生成独立 `ts-species-record/1` 文件。参与反应的催化剂与 spectator
应位于适当一侧。`reaction.validate` 检查封闭边界；电子/质子 reservoir 需要独立模型，
当前返回 unsupported。

`reaction.mapping.generate` 提出图编辑最小值，搜索受 `max_states` 和 `max_candidates`
限制。其目标函数不是机理可能性。对称氢可能产生多个等价映射；截断搜索不能证明唯一性
或全局最优。显式 SMILES map label 会被记录，但在 version 1 中不约束图编辑搜索。

`reaction.bond_changes` 接受完整显式 `mapping`，或一个 mapping Artifact 加显式、从零
开始的 `candidate_index`。它返回新形成、断裂和键级改变的键，以及反应中心原子。所选
对应关系仍是 Agent 声明，不是机理证明。

`structure.reindex` 把该对应关系应用到有序 XYZ species list，并写出两个对齐的端点文件。
XYZ 原子顺序必须与定义 mapping 的图一致；元素一致本身不能证明两个同元素原子身份正确。

`structure.assemble_fragments` 使用显式旋转矩阵和以 angstrom 为单位的平移。它可以评估
多个 `placement_candidates` 并标记过近的片段间接触，但不执行优化或自动复合物搜索。
后续优化/CREST/NEB 属于独立科学选择。反射操作会改变立体化学，因此被拒绝。

`species.identity` 依据 isomeric graph、同位素、电荷和多重度比较 SpeciesRecord。它不
解析未指定立体化学，也不分类构象。几何 identity 使用现有 `artifact.compare`，并提供合适的
mapping、立体化学检查和物理阈值。
