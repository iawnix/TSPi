# TSPi Skills

[English](README.md) | [简体中文](README.zh-CN.md)

TSPi 提供一个领域无关的 Research Harness；当前随附的 17 个 Skill 组成计算化学能力包。`orchestration` 和 `research-state` 是两个核心系统 Skill：它们的摘要始终注入 system prompt，完整参考资料按需提供给 Agent。绑定 Provider 的 Skill 与 Provider 一起位于 `extensions/`。
Research State Skill 管理规范 ResearchMap 合同；编排 Skill 选择下一项有边界的任务；
科学与交付 Skill 各自处理一种方法或输出问题，不再重复定义状态。

| Skill | 职责 |
| --- | --- |
| [research-state](research-state/SKILL.zh-CN.md) | ResearchMap 读取、校验、Finding、Gate 与原子变更 |
| [orchestration](orchestration/SKILL.zh-CN.md) | 任务规划、分支、恢复、评审与停止 |
| [candidate-generation](../extensions/chemical/skills/candidate-generation/SKILL.zh-CN.md) | TS 候选构造、扫描、QST、NEB 与采样 |
| [validation](../extensions/chemical/skills/validation/SKILL.zh-CN.md) | 鞍点、振动模式、结构、电子态与立体化学验证 |
| [irc](../extensions/chemical/skills/irc/SKILL.zh-CN.md) | 双向路径与端点身份 |
| [energetics](../extensions/chemical/skills/energetics/SKILL.zh-CN.md) | 能量、热校正、势垒、有限动力学与能量剖面 |
| [method-selection](../extensions/chemical/skills/method-selection/SKILL.zh-CN.md) | 科学方法、Backend capability 与计算环境选择 |
| [cf22d](../extensions/chemical/skills/cf22d/SKILL.zh-CN.md) | 已注册的 PySCF/CF22D 工作流与运行环境就绪检查 |
| [xtb](../extensions/chemical/skills/xtb/SKILL.zh-CN.md) | 已注册的 xTB 计算 |
| [crest](../extensions/chemical/skills/crest/SKILL.zh-CN.md) | CREST 构象集合 |
| [qbics](../extensions/chemical/skills/qbics/SKILL.zh-CN.md) | QBICS 方法建议与实时 capability 发现 |
| [gaussian](../extensions/chemical/skills/gaussian/SKILL.zh-CN.md) | Gaussian 输入、执行、解析与输出检查 |
| [report](../extensions/chemical/skills/report/SKILL.zh-CN.md) | 绑定 ResearchMap revision 的研究报告 |
| [render](../extensions/chemical/skills/render/SKILL.zh-CN.md) | 分子图像、动画、对比图与科学曲线 |
| [email](../extensions/email/SKILL.zh-CN.md) | 按配置发送通知与报告 |
| [mechanism-reasoning](../extensions/chemical/skills/mechanism-reasoning/SKILL.zh-CN.md) | 机理假设、映射、基元步骤与替代路径 |
| [chemical-input](../extensions/chemical/skills/chemical-input/SKILL.zh-CN.md) | 自然语言化学名称、结构候选与输入确认 |

Harness 可以承载化学、数据分析、模拟或其他研究领域的 Skill。当前过渡态能力包中的
Skill 仍保持清楚边界：候选生成产生结构，TS 验证建立鞍点证据，IRC 归属端点，能量学
比较校正后的物理量。Root 通过 Research State 把核验后的输出记录到同一个 ResearchMap。

每个 Skill 都有内容对应的英文和中文入口，每份详细参考文档也同时维护英文与简体中文
版本；两种语言的入口只链接同语言参考文档。常用术语见
[术语表](research-state/references/glossary.zh-CN.md)。
