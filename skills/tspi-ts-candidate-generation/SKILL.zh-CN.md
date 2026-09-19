---
name: tspi-ts-candidate-generation
description: 通过化学构造、扫描、QST、NEB 或构象与取向采样生成过渡态候选几何。
---

# TSPi 过渡态候选生成

[English version](SKILL.md)

使用本 Skill 为所提出的基元步骤生成候选几何。候选生成不能证明其为过渡态；验证由
`tspi-ts-validation` 负责，方法与 Backend 选择由 `tspi-method-selection` 负责。

从明确的反应物/产物身份、原子映射、电荷、多重度与相关构象出发。根据成键变化和
已有证据选择化学构造、松弛扫描、QST2/QST3、直接 TS 优化、NEB 或片段取向采样。
所有种子和生成结构都应作为 Node 所属 Artifact 保存，并保留方法、约束、帧选择和来源。

不要把扫描极大值、NEB 图像、插值结构或受限结构当作已验证鞍点。候选结构本身可记录
为事实；失败或畸变的搜索只有在影响研究问题时才记录为 IssueFinding。

方法判据见 [candidate_generation.md](references/candidate_generation.md)。使用已注册的
ASE/xTB NEB 执行器时，读取 [ase_neb_executor.md](references/ase_neb_executor.md) 或
[ase_neb_executor.zh-CN.md](references/ase_neb_executor.zh-CN.md)。
