# 结构准备

inspect --smiles 检查 RDKit 图、分子式、电荷及未指定立体化学；不核实名称对应关系。
seed --smiles --charge --multiplicity --output-dir 使用固定 ETKDG 随机种子生成显式氢 XYZ。
输出目录必须为空；电子数与多重度奇偶不符会拒绝。每个 XYZ 有 SHA256 和异构体来源。
未指定立体化学时可显式 --enumerate-stereo，保留全部有界候选，不作为单一身份确认。
reaction --smiles 接受映射的 reactants>>products，检查总元素、电荷与双射映射并列出键变化。
原子映射检查覆盖显式原子；隐式氢的归属和转移不是已验证结果。
单分子优化不需要 reaction 子命令。seed、映射与几何有效性不能替代量化计算和机理判断。
