# Skill 目录与加载语言

[English](README.md) | [简体中文](README.zh-CN.md)

**默认加载英文 `SKILL.md`。** Pi 先发现名称、描述和文件路径，Agent 按需读取正文与参考资料。
`SKILL.zh-CN.md` 是中文对照，不会根据对话语言自动切换，也不会作为重复 Skill 自动加载。
需要时 Agent 可以显式读取中文文件；回答和报告可以按用户要求使用中文。
实现与资源维护见[Skill 与科学执行目录](../docs/EXTENSIONS.zh-CN.md)。

Skill 提供方法指导，可以调用随附脚本，也可以编写任务所需的输入和分析脚本；
`execution.json` 的便捷入口不构成能力上限。

| Skill | 用途 |
| --- | --- |
| [email](email/SKILL.zh-CN.md) | 通过配置的 SMTP 或 ClawEmail 发送用户要求的研究邮件，保存可恢复、可去重的发送回执。 |
| [research-memory](research-memory/SKILL.zh-CN.md) | 用持久问题 Node、显式关系、执行观察与不可变 Result 恢复和推进研究。 |
| [research-workflow](research-workflow/SKILL.zh-CN.md) | 在 Pi 原生循环中协调研究问题、领域 Skill、持久 Job、材料和有依据的 Result。 |
| [candidate-generation](../domains/chemical/skills/candidate-generation/SKILL.zh-CN.md) | 通过化学构造、扫描、QST、NEB 或构象与取向采样生成过渡态候选几何。 |
| [cf22d](../domains/chemical/skills/cf22d/SKILL.zh-CN.md) | 执行并解释 PySCF CF22D 单点、结构优化、过渡态、频率和 RRHO 热化学校正。 |
| [chemical-input](../domains/chemical/skills/chemical-input/SKILL.zh-CN.md) | 通过可执行 helper 解析化学名称、检查分子图、生成可重放的初始几何，并核验显式反应原子映射。 |
| [crest](../domains/chemical/skills/crest/SKILL.zh-CN.md) | 运行和评估 CREST 构象搜索，并保存构象集合、能量、设置、来源与选择理由。 |
| [energetics](../domains/chemical/skills/energetics/SKILL.zh-CN.md) | 评估电子能、ZPE 与热校正、自由能和反应能、势垒、有限范围的 TST 速率及能量剖面。 |
| [gaussian](../domains/chemical/skills/gaussian/SKILL.zh-CN.md) | 准备、执行并检查 Gaussian 单点、优化、频率、过渡态、IRC、QST 和显式扫描输入。 |
| [irc](../domains/chemical/skills/irc/SKILL.zh-CN.md) | 规划和评估双向内禀反应坐标计算，并将端点归属到已声明的分子势阱。 |
| [mechanism-reasoning](../domains/chemical/skills/mechanism-reasoning/SKILL.zh-CN.md) | 使用明确的物种身份、原子映射、基元步骤、替代假设与可证伪条件形成、比较并修订反应机理假设。 |
| [method-selection](../domains/chemical/skills/method-selection/SKILL.zh-CN.md) | 选择科学方法并准备命名计算环境；用户已经指定方法时同样用于执行准备。 |
| [qbics](../domains/chemical/skills/qbics/SKILL.zh-CN.md) | 判断 QBICS 的适用性，核实已安装命令、输入与验证需求后执行有界研究 Job。 |
| [report](../domains/chemical/skills/report/SKILL.zh-CN.md) | 根据研究证据编写图文报告，包含分子结构、能量曲线、数据表、方法、结论和可追溯的来源。 |
| [validation](../domains/chemical/skills/validation/SKILL.zh-CN.md) | 根据鞍点、目标振动模式、结构、电子态与立体化学证据验证过渡态候选。 |
| [xtb](../domains/chemical/skills/xtb/SKILL.zh-CN.md) | 使用 xTB 进行低成本结构筛选、单点、优化、频率、约束扫描和分子动力学，并分析原始输出。 |
