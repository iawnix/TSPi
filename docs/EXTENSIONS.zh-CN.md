# Skill 与科学执行目录

[English](EXTENSIONS.md) | [简体中文](EXTENSIONS.zh-CN.md)

项目将方法指导、便捷执行入口和实际计算环境分别维护。Agent 可以根据研究问题编写输入与脚本，
通过通用 Job 执行；内置入口不构成能力白名单，也不规定研究步骤。

## Skill 发现与语言

根 `package.json` 的 `pi.skills` 声明 `skills/` 和 `domains/chemical/skills/`。
`apps/agent/resources/skills.mjs` 校验发布资源后调用 Pi 的 `loadSkills`，并关闭默认目录发现。
Pi 从 Skill 目录的 `SKILL.md` 发现技能；当前这些入口使用英文。
名称、描述和文件位置用于技能选择，正文由 Agent 按需读取，参考资料继续按需展开。

`SKILL.zh-CN.md` 是供阅读和维护的中文对照，不会因用户使用中文或系统 locale 为中文就替换英文入口，
也不会作为第二个独立 Skill 自动加载。Agent 可以在需要时显式读取中文文件；回复和报告语言遵循用户要求。
中英文须同步维护；仅修复中文不能修复默认加载的英文指导。完整入口见 [Skill 目录](../skills/README.zh-CN.md)。


## 系统提示词

`apps/agent/pi/setup.mjs` 将工作目录、`prompts/research-agent.md` 和已发现的 Skill 描述组装为系统提示词。
`prompts/research-agent.zh-CN.md` 是中文维护对照，不会同时注入，也不会随会话语言自动切换。
`/sys-prompt` 可以检查当前 worker 的实际提示词及来源。

系统提示词保留跨任务通用的决策规则：指令优先级、研究对象、执行归属、授权与预算、证据标准、
结果纠正和沟通。具体科学方法与完整工具示例留在按需读取的 Skill 中。
工作区 AGENTS.md 由提示词要求 Agent 主动读取，不在上述组装步骤中自动拼接。
每次模型请求前另外注入有限的研究快照；它提供当前记录，不赋予新指令或行动授权。

资源摘要检查能验证加载字节，确定性测试能验证注入与记录行为；这些检查不能证明模型会遵循所有准则，
也不能替代实际费用限制或执行权限控制。

## execution.json 的作用

根 `package.json` 的 `researchAgent.execution` 指向 `domains/chemical/execution.json`。
Python 的 `backend/src/research_agent/application/execution_catalog.py` 独立读取与验证它。
该文件声明：

- `executors`：便捷执行入口的 ID/版本、脚本、参数模板、输入角色、输出文件、依赖和资源摘要。
- `validators`：针对具体证据的检查脚本及输入契约。
- `acceptance_profiles`：特定交付物的检查清单；适用范围由具体 profile 决定。

它不加载 Skill，不编排 workflow，也不把 Agent 限制在这些脚本内。
选择 `--executor` 或 `validator_id` 时必须使用已登记 ID 和版本；这是所选便捷入口的契约。
对目录外的方法，可以直接通过 `job_start` 提交明确的 command、inputs、outputs 和 platform，
或使用准备器的 `--script <file.py> --backend <binding>`。无需为每个新任务修改此 JSON。
实际程序、Python、激活脚本和计算资源由安装级 `etc/job.toml` 的环境绑定配置。

完整的准备、提交、收集与恢复过程见[科学计算指南](SCIENTIFIC_CAPABILITIES_OPERATIONS.zh-CN.md)。

## 维护

`config/resources.json` 保存随包 Skill、参考资料、脚本和提示词的资源摘要；执行目录另行固定其脚本依赖。
修改资源后运行：

```bash
python3 scripts/update_resources.py
python3 scripts/update_resources.py --check
python3 tools/lint_skills.py
```

新增 Skill 放入已声明根目录，并提供中英文入口及对应参考资料。
仅在新增可复用的便捷执行入口时更新执行目录。核心工具装配属于 `apps/agent/`，
不使用旧的 extension manifest、动态 server allowlist 或 provider 注册流程。
