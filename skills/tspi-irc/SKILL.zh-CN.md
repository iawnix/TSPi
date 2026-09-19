---
name: tspi-irc
description: 规划和评估双向内禀反应坐标计算，并将端点归属到已声明的分子势阱。
---

# TSPi IRC

[English version](SKILL.md)

使用本 Skill 处理正向/反向 IRC 的设计、运行结果解释、路径完成性、端点提取与端点身份。
Gaussian Skill 负责检查 Gaussian 文件，本 Skill 负责路径的化学含义。

从已验证的鞍点候选出发并保留路径方向。核对 IRC 起点与该结构是否一致，分别检查两个
方向的终止与路径完整性、末端几何和梯度，并判断盆地归属前是否需要优化端点。使用明确
的目标 Artifact，通过原子映射、关键内坐标、立体化学和确定性结构比较核验每个端点。

按方向分别记录路径和端点事实。缺失或矛盾的端点证据属于 IssueFinding，但不会隐式
改变 Node 或 Claim 状态。详见 [irc_validation.md](references/irc_validation.md)。
