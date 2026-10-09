---
name: energetics
description: 评估电子能、ZPE 与热校正、自由能和反应能、势垒、有限范围的 TST 速率及能量剖面。
---

# ResearchAgent 能量学

[English version](SKILL.md)

使用本 Skill 处理 `E`、`E+ZPE`、`H`、`G`、反应能与活化能、标准态校正、有限范围的
过渡态理论速率和能量剖面。必须明确能量类型、单位、温度、压力或浓度、标准态、相态、
溶剂、方法、电子态、化学计量与频率处理。

只有结构、原子顺序、方法和声明的组合处理一致时，才能组合电子与热结果。不要用电子
势垒替代 Gibbs 势垒，不要推断未支持的同位素校正，也不要把定性路径枚举当作动力学。
数值与局限应分别记录为引用来源 Artifact 的研究记录。

科学检查及执行边界见 [energetics.zh-CN.md](references/energetics.zh-CN.md)。本 Skill 不提供可调用的
热化学、动力学或网络分析工具；记录结论前需执行具体分析并保存证据。
