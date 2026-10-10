# 结构准备

inspect --smiles 检查 RDKit 图、分子式、电荷及未指定立体化学。
seed --smiles --charge --multiplicity --output-dir 使用固定 ETKDG 随机种子生成显式氢 XYZ。
输出目录必须为空；电子数与多重度奇偶不符会拒绝。每个 XYZ 有 SHA256 和异构体来源。
结合任务选择立体异构体，或用 --enumerate-stereo 分别研究候选。source=llm 无需另行确认。
reaction --smiles 接受映射的 reactants>>products，检查总元素、电荷与双射映射并列出键变化。
`--transformation` 可提供 JSON 对象：kind=diels_alder 带二烯/亲二烯体 map ID 与 forming_bonds；
或 kind=explicit 带 bond_changes 及可选 hydrogen_changes。DA 检查要求其余键和逐原子氢数保留。
未声明变换时不判断反应类型；个体隐式氢对应与立体化学机理仍未验证。输出使用 chemical-reaction/2 的分范围 checks。
单分子优化不需要 reaction 子命令。seed、映射与几何有效性不能替代量化计算和机理判断。

## 结构对照

inspect 和 seed 包含 `chemical-identity/1` 对象，保存规范异构 SMILES、电荷、RDKit
版本及内容身份。将选用目标登记为 Artifact，通过 Node 的 `subjects.target` 引用。
准备 `chemical.compare@1`，指定 `--input target=<inspect.json>` 与
`--input actual=<结构JSON或几何XYZ>`。XYZ 需追加
`-- --actual-format xyz --charge <实际电荷>`；默认读取结构 JSON。
收集 `results/comparison.json`，其中记录 match、mismatch 或 indeterminate、
对照结构及检查范围。XYZ 的键级由几何推断。用 `check_refs` 引用检查材料，
用 `subjects` 区分目标和计算结构；利用差异指导研究，检查不限制记录结论或继续工作。
