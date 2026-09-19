---
name: tspi-energetics
description: 评估电子能、ZPE 与热校正、自由能和反应能、势垒、有限范围的 TST 速率及能量剖面。
---

# TSPi 能量学

[English version](SKILL.md)

使用本 Skill 处理 `E`、`E+ZPE`、`H`、`G`、反应能与活化能、标准态校正、有限范围的
过渡态理论速率和能量剖面。必须明确能量类型、单位、温度、压力或浓度、标准态、相态、
溶剂、方法、电子态、化学计量与频率处理。

只有结构、原子顺序、方法和声明的组合处理一致时，才能组合电子与热结果。不要用电子
势垒替代 Gibbs 势垒，不要推断未支持的同位素校正，也不要把定性路径枚举当作动力学。
数值与局限应分别记录为引用来源 Artifact 的 Finding。

支持的热化学、势垒、速率、分支、网络与剖面合同见
[energetics.zh-CN.md](references/energetics.zh-CN.md)。
