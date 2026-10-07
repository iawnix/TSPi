# Molecular preparation / 分子准备

Use the chemical-input Skill's executable scripts/prepare.py through bash.
resolve handles names; inspect checks SMILES; seed writes reproducible explicit-H
XYZ with declared charge/multiplicity. reaction checks an explicit mapped
reactants>>products expression for atom coverage, composition, charge and bond changes.

Agent selects the mapping and research scope. Explicitly enumerate unspecified
stereoisomers when they are alternatives under study. Separately explore diene
conformers and intermolecular approach geometries; an isomer seed does not sample
the conformational landscape. Keep atom order and map correspondence with every XYZ.

使用 chemical-input 的实际 CLI，保留来源、原子编号与映射。名称解析、初始几何、
反应对应关系是不同证据；不要把图变化或嵌入结果当成机理证明。
旧 reaction.parse/structure.* provider 接口已移除，不再尝试发现这些工作流。
