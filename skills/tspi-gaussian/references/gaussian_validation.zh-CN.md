# Gaussian 验证

向 map 添加 Finding 前，先核验已收集的主要 Gaussian 输出。

## 程序与 Intent

对照不可变 calculation intent 检查正常终止、route、方法/基组、电荷、多重度、溶剂化/
环境、色散、grid、SCF 处理、优化与频率关键词、约束、资源和重要 warning。当 adapter 能
确定输入错误时，应在远端提交前拒绝。

## 驻点

将正常终止、驻点确认、优化收敛、虚频数量与方法一致性记录为不同 FactFinding。普通一阶
鞍点必须准确具有一个虚频。频率、位移与可视化分别记录为有来源支持的值；只有将位移与
Claim 中的成键变化联系后，才能把它作为反应坐标事实。

## 局限与条件

当 SCF 不稳定、自旋污染、波函数不稳定、电子态歧义、近简并、积分 warning 或方法敏感性
影响解释时，将其记录为 IssueFinding。区分 E、E+ZPE、H 与 G，并保留温度、压力、标准态、
scaling 和缺失校正。只有可见 criterion 与 evaluation 有助于关闭或评估研究问题时，才
使用 NodeGate 或 ClaimGate。
