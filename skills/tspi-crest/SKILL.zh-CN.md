---
name: tspi-crest
description: 运行和评估 CREST 构象搜索，并保存构象集合、能量、设置、来源与选择理由。
---

# TSPi CREST

[English version](SKILL.md)

使用本 Skill 处理已注册的 `crest.conformer_search` capability。CREST 负责构象集合探索；
CREST 搜索之外的 xTB 计算由 `tspi-xtb` 负责。

绑定一个 XYZ Artifact，并显式给出电荷、未成对电子数、xTB 方法、搜索与优化级别、线程和
溶剂设置。核验正常终止与完整的主要输出集，检查构象数和能量表行数一致，并确保后续使用
的每个成员保持原子数、顺序与身份。

将集合大小、相对能量表、所选几何和选择理由记录为不同事实。调度器成功但缺失主要输出
属于运行故障，不是空构象集合。详见 [crest_ensemble.md](references/crest_ensemble.md)。
