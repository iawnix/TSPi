# TSPi Skills

[English](README.md) | [简体中文](README.zh-CN.md)

TSPi 提供 16 个职责明确的 Skill。Research Kernel Skill 管理规范 ResearchMap 合同；
编排 Skill 选择下一项有边界的任务；科学与交付 Skill 各自处理一种方法或输出问题，不再
重复定义状态。

| Skill | 职责 |
| --- | --- |
| [tspi-research-kernel](tspi-research-kernel/SKILL.zh-CN.md) | ResearchMap 读取、校验、Finding、Gate 与原子变更 |
| [tspi-orchestration](tspi-orchestration/SKILL.zh-CN.md) | 任务规划、分支、恢复、评审与停止 |
| [tspi-ts-candidate-generation](tspi-ts-candidate-generation/SKILL.zh-CN.md) | TS 候选构造、扫描、QST、NEB 与采样 |
| [tspi-ts-validation](tspi-ts-validation/SKILL.zh-CN.md) | 鞍点、振动模式、结构、电子态与立体化学验证 |
| [tspi-irc](tspi-irc/SKILL.zh-CN.md) | 双向路径与端点身份 |
| [tspi-energetics](tspi-energetics/SKILL.zh-CN.md) | 能量、热校正、势垒、有限动力学与能量剖面 |
| [tspi-method-selection](tspi-method-selection/SKILL.zh-CN.md) | 科学方法、Backend capability 与计算环境选择 |
| [cf22d](cf22d/SKILL.zh-CN.md) | 已注册的 PySCF/CF22D 工作流与运行环境就绪检查 |
| [tspi-xtb](tspi-xtb/SKILL.zh-CN.md) | 已注册的 xTB 计算 |
| [tspi-crest](tspi-crest/SKILL.zh-CN.md) | CREST 构象集合 |
| [tspi-qbics](tspi-qbics/SKILL.zh-CN.md) | QBICS 方法建议与实时 capability 发现 |
| [tspi-gaussian](tspi-gaussian/SKILL.zh-CN.md) | Gaussian 输入、执行、解析与输出检查 |
| [tspi-report](tspi-report/SKILL.zh-CN.md) | 绑定 ResearchMap revision 的研究报告 |
| [tspi-render](tspi-render/SKILL.zh-CN.md) | 分子图像、动画、对比图与科学曲线 |
| [tspi-email](tspi-email/SKILL.zh-CN.md) | 按配置发送通知与报告 |
| [tspi-mechanism-reasoning](tspi-mechanism-reasoning/SKILL.zh-CN.md) | 机理假设、映射、基元步骤与替代路径 |

一个过渡态研究可以调用多个 Skill，但它们各自保持清楚边界：候选生成产生结构，TS 验证
建立鞍点证据，IRC 归属端点，能量学比较校正后的物理量。Root 通过 Kernel 把核验后的
输出记录到同一个 ResearchMap。

每个 Skill 都有内容对应的英文和中文入口，每份详细参考文档也同时维护英文与简体中文
版本；两种语言的入口只链接同语言参考文档。常用术语见
[术语表](tspi-research-kernel/references/glossary.zh-CN.md)。
