# TSPi Skills

[English](README.md) | [简体中文](README.zh-CN.md)

TSPi 提供九个 Skill，用于规划研究、运行计算、检查结果，以及制作图像和报告。
编排 Skill 管理研究流程；需要具体方法或输出时，加载相应的专用 Skill。

| Skill | 用途 |
| --- | --- |
| [tspi-orchestration](tspi-orchestration/SKILL.zh-CN.md) | 研究问题、工作区记录、Claim 验证和恢复 |
| [tspi-transition-state-search](tspi-transition-state-search/SKILL.zh-CN.md) | 候选构造、QST、扫描、NEB、构象和搜索策略 |
| [tspi-xtb](tspi-xtb/SKILL.zh-CN.md) | xTB 计算与 CREST 构象搜索 |
| [tspi-gaussian](tspi-gaussian/SKILL.zh-CN.md) | Gaussian 输入、优化、频率和 IRC |
| [tspi-connectivity](tspi-connectivity/SKILL.zh-CN.md) | IRC 端点、原子映射、立体化学和结构比较 |
| [tspi-mechanism](tspi-mechanism/SKILL.zh-CN.md) | 反应定义、显式原子映射、基元步骤和机理比较 |
| [tspi-render](tspi-render/SKILL.zh-CN.md) | 分子图像、动画、结构对比图和科学曲线 |
| [tspi-report](tspi-report/SKILL.zh-CN.md) | 包含证据、计算历史和图像的研究报告 |
| [tspi-email](tspi-email/SKILL.zh-CN.md) | 按配置发送研究通知和报告 |

例如，Gaussian 过渡态研究使用编排 Skill 组织问题，使用过渡态搜索 Skill 选择策略，
通过 Gaussian 和连通性 Skill 评估结果，最后使用渲染与报告 Skill 展示研究成果。
从 SMILES 生成初始结构和导入输入文件的方法见
[结构与产物工具](tspi-orchestration/references/artifact_tools.md)。

每个 Skill 都有内容对应的英文和中文入口。详细工具字段和方法参考资料由相应
Skill 链接，常用术语见[术语表](tspi-orchestration/references/glossary.zh-CN.md)。
