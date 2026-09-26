# 名称解析合同

`chemical.name.resolve@1` 是确定性分析能力。它接收原始名称，也可以核验显式提供的
候选 SMILES。解析器必须报告实现和版本；模型生成的候选在确定性解析器或用户明确确认
之前始终标记为 `draft`。

结果区分 `resolved`、`ambiguous`、`draft` 和 `unresolved`，并包含 canonical/isomeric
SMILES、分子式、形式电荷、可选 InChI/InChIKey、未指定的立体中心和诊断。解析器缺失时
返回结构化 capability gap，不能借此默写一个结构。

名称查询和结构身份与 3D 生成是不同步骤。候选确认后再调用 `artifact_seed`，并使用已有分析
能力验证反应守恒和 atom mapping。
