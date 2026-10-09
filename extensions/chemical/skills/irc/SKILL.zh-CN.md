---
name: irc
description: 规划和评估双向内禀反应坐标计算，并将端点归属到已声明的分子势阱。
---

# TSPi IRC

[English version](SKILL.md)

使用本 Skill 处理正向/反向 IRC 的设计、运行结果解释、路径完成性、端点提取与端点身份。
Gaussian Skill 负责检查 Gaussian 文件，本 Skill 负责路径的化学含义。

Gaussian 路径使用 `chemical.path-irc` Job 入口，根据已验证鞍点的检查点和路径 spec
准备双向输入，再分别用 `chemical.gaussian-input` 执行。输入准备及证据绑定见
[可执行路径流程](../candidate-generation/references/gaussian_path.zh-CN.md)。
内置路径构造器限于其声明的 DA 范围，其他机理需要明确的方法及经过验证的 runner。

从已验证的鞍点候选出发并保留路径方向。核对 IRC 起点与该结构是否一致，分别检查两个
方向的终止与路径完整性、末端几何和梯度，并判断盆地归属前是否需要优化端点。使用明确
的目标 Artifact，通过原子映射、关键内坐标、立体化学和确定性结构比较核验每个端点。

按方向分别记录路径和端点事实。缺失或矛盾的端点证据属于 IssueFinding，但不会隐式
改变 Node 或 Claim 状态。详见
[irc_validation.zh-CN.md](references/irc_validation.zh-CN.md)。
