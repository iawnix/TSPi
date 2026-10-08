# 过渡态验证

过渡态验证把程序完成、驻点证据、振动模式归属、结构 identity 与科学解释分开。任何单一
解析器标记都不能同时建立这些结论。

[Gaussian runner](../../gaussian/SKILL.zh-CN.md) 使用 `gaussian_io.py::parse_log` 写出
`parsed.json`，提取终止、收敛、驻点标记、频率、几何及最终谐振表的笛卡尔模式向量。
其 `section_index` 参数从零开始。选择相关 section，并把输出 route、电荷、多重度、
方法和基组与输入比较。

对经典一阶鞍点，要求优化收敛，并存在一个表示所提出基元步骤的虚频模式。数值噪声、约束、
平坦模式与竞争虚频必须保持可见。检查位移向量，不能只依赖虚频数量。

声明的 DA 路径可用 `chemical.gaussian_saddle` 比对已登记 spec 与收集的原始 log，检查方法/资源、
收敛、完整频率表及两条成键的同时位移。入口见 [可执行路径](../../candidate-generation/references/gaussian_path.zh-CN.md)。
归一化位移阈值属于有限模式检查，不证明整个机理。旧 `chemical.gaussian_frequency` 仍只检查正常终止与一个负频率。

核验元素计数、原子 mapping、电荷、多重度、电子态、关键距离与二面角、立体化学，并确认
没有意外片段或构象变化。将 SCF 不稳定、自旋污染、态歧义、方法敏感性与缺失稳健性检查
作为不同问题处理。

把每个已核验属性记录为 FactFinding，并引用主要输出与分析 Artifact。缺失、冲突或歧义
证据记录为 IssueFinding。这些记录为之后的状态决策提供信息，但不会自动改变 Node 或
Claim。IRC 连通性是独立验证维度，由 `irc` 处理。
