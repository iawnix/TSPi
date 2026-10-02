# 热化学、基元动力学与网络

`thermochemistry.evaluate` 接受一个 `electronic` Gaussian log 和可选 `thermal` log。
指定 `species_key`、`quantity`（`E`、`E_ZPE`、`H`、`G`）、`electronic_state`、
`stationary_kind`、`methods` 与条件。方法字符串标识 route 中准确的方法/基组 token，例如
`B3LYP/6-31G(d)`。使用不同来源时要求 `methods.composite=true`，且按原子顺序排列的
几何在显式阈值内一致。不同方法会被记录，不会静默混合。这里 XYZ/Gaussian 几何不编码
同位素质量；同位素特定 RRHO 与 KIE 不在 version 1 范围内。

电子能提取当前支持匹配的 HF/Kohn-Sham SCF 总能。不能把相关方法的参考 SCF 能量报告为
其 MP2/CCSD(T) 能量；这些输出需要专用能量解析器。

条件包括 kelvin 温度、相态、相关时的溶液溶剂、`source_standard_state` 与目标
`standard_state`。每个标准态包含 `kind`、`value`、`unit`：压力（`bar`、`atm`、`Pa`）
或浓度（`mol/L`）。每个 species 的 G 转换为 `RT ln(c_target/c_source)`，不应用于 E、
E+ZPE 或 H。实际反应物浓度是独立速率输入。

默认模型使用 Gaussian log 在记录温度与压力下的已解析校正。`model.kind=rrho` 使用 ASE
理想气体热化学，并显式提供 `geometry`（`monatomic`、`linear`、`nonlinear`）、旋转
`symmetry_number` 和可选 `frequency_scale`。TS 准确排除一个不稳定模式；极小点不能有
不稳定模式。低频非谐性、受阻转子、构象集合、准谐模型与不确定性传播不会自动推断。

`barrier.evaluate` 要求反应物、产物与 TS thermal Artifact。显式化学计量系数对每个
提供的 Artifact 默认为一。Quantity、条件、方法与 scaling convention 必须一致。检查
组成/电荷与可能的自旋耦合。自旋兼容不能证明绝热势能面连续。动力学中电子势垒绝不能
替代 Gibbs 势垒。

`kinetics.tst` 使用浓度形式的基元 TST：

`k_m = κ k_B T/h · (c°)^(1−m) · exp(−ΔG‡/RT)`。

一级反应单位为 `s^-1`；二级反应为 `L mol^-1 s^-1`。可选 `concentrations_molar` 生成
单位为 `mol/L/s` 的独立速率。偏离默认 κ=1 时必须显式提供 κ。不会推断隧穿/再穿越或扩散
校正。负势垒会被标记为不适合简单 activated-TST 解释；极端速率常数仍以 ln k 提供。

`kinetics.branching` 只对同一个已平衡前体、不可逆产物且产物不互相转化的情形计算归一化
初始速率权重。这些假设必须显式满足。循环、耗尽与随时间变化的产率需要超出本 capability
的动力学模型。

`mechanism.step.define` 记录平衡的 ReactionSpec、可逆性以及可选结构 audit/势垒/速率
证据；缺失证据保持可见。`mechanism.network.assemble` 将所选 StepRecord 组合为化学计量
超边，允许平行步骤、中间体、可逆性与循环。使用以 `step/local_species` 为 key 的显式
`species_aliases` 解决 key 冲突。`mechanism.network.audit` 检查平衡、identity 冲突与
缺失证据。可选的有界路径枚举只表示定性可用性，不模拟耗尽，也不按动力学偏好排序路径。

`mechanism.energy_profile` 要求选定路径和 `initial_composition`。它在同一参考上累积 ΔG
与局部势垒，同时保留化学计量参与者和 spectator pool。生成的 `energy_profile.json`
使用现有 `ts-curve-data/1` 合同，可传给 `artifact_render curve`。该剖面是所选比较，不声称机理
发现完整。报告与 Node Web 详情把分析链接回来源文件和 Finding。
