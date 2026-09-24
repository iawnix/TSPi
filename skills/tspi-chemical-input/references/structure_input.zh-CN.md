# 确认后的结构输入

`ts_seed` 使用确认后的 isomeric SMILES，并显式声明电荷和多重度。使用计算输入前检查
未指定立体化学和生成的 3D seed。反应必须先运行 `reaction.parse` 检查封闭体系守恒，
再生成 mapping 候选，并在提取键变化前显式选择 mapping。
