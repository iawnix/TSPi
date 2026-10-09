---
name: candidate-generation
description: 通过化学构造、扫描、QST、NEB 或构象与取向采样生成过渡态候选几何。
---

# ResearchAgent 过渡态候选生成

[English version](SKILL.md)

使用本 Skill 为所提出的基元步骤生成候选几何。候选生成不能证明其为过渡态；验证由
`validation` 负责，方法与 Backend 选择由 `method-selection` 负责。

从明确的反应物/产物身份、原子映射、电荷、多重度与相关构象出发。根据成键变化和
已有证据选择化学构造、松弛扫描、QST2/QST3、直接 TS 优化、NEB 或片段取向采样。
所有种子和生成结构都应作为研究 Node 所属 Artifact 保存，并保留方法、约束、帧选择和来源。

不要把扫描极大值、NEB 图像、插值结构或受限结构当作已验证鞍点。候选结构本身可记录
为事实；失败或畸变的搜索只有在影响研究问题时才记录为研究记录。

显式 DA假设可用 [prepare_path.py](scripts/prepare_path.py) 生成原子顺序绑定的 QST2 候选与 IRC 输入。
可执行步骤与注册验证器见 [gaussian_path.zh-CN.md](references/gaussian_path.zh-CN.md)，不代表机理覆盖完备。Skill 本身没有脚本时仍可能使用共享 runner 或已安装软件，
先检查这些入口再判断方法是否不可用。
方法判据见 [candidate_generation.zh-CN.md](references/candidate_generation.zh-CN.md)，
NEB 可用性与前提见 [ase_neb_executor.zh-CN.md](references/ase_neb_executor.zh-CN.md)。
