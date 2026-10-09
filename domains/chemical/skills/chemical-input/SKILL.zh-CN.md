---
name: chemical-input
description: 通过可执行 helper 解析化学名称、检查分子图、生成可重放的初始几何，并核验显式反应原子映射。
---

# 化学输入

[English version](SKILL.md)

名称、SMILES、结构描述或反应输入使用本 Skill。准备 `chemical.resolve`、
`chemical.inspect`、`chemical.seed` 或 `chemical.reaction` 的版本 `1` 请求，再通过
`job_start` 执行。目标环境的 `structure` Python 绑定提供 RDKit。
保留原始名称、结构来源、电荷、多重度和 helper JSON 作为证据。

单分子计算先确认身份、检查分子图，再准备 seed；优化和单点能不需要反应映射。
helper 内置明确的中性水规则（water/H2O/水/水分子 → O）。其他名称通过配置的
PubChem/OPSIN 查询；--lookup-name 可提供翻译或规范化名称，同时保留原文。
用户提供的结构可以直接检查。模型给出的 SMILES 通过图校验，不等于名称身份已确认。

```text
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.resolve --version 1 --output prepared/身份.json -- --name water
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.inspect --version 1 --output prepared/graph.json -- --smiles O
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.seed --version 1 --output prepared/seed.json -- --smiles O --charge 0 --multiplicity 1
```

每条命令只准备请求。将返回的文件和摘要提交，再收集 Job；
生成的结构和 JSON 保留 Job 与环境绑定，seed Job 会收集每个生成的 XYZ。

反应研究逐一解析/检查物种，再用 reaction 子命令核验组成、电荷和显式映射，并列出键变化。
输出为 `chemical-reaction/2` 的分范围 `checks`，不再使用全局 validated。未提供 `--transformation <JSON>` 时，
预期成断键模式未评估；声明 `diels_alder` 可检查全部键变化、取代基保留与逐原子氢计数，
`explicit` 可声明其他预期键/氢变化。
研究质子转移时应显式映射氢原子。

```text
"$RESEARCH_AGENT_PYTHON" -m research_agent.application.executors --config "$RESEARCH_AGENT_JOB_CONFIG" --environment local --executor chemical.reaction --version 1 --output prepared/reaction.json -- --smiles '<mapped-reactants>><mapped-products>'
```

名称无法解析或存在实质不同的身份时，进行有界查询或澄清。
若研究范围本就包含未指定立体化学的候选，可用 seed --enumerate-stereo 枚举至多
16 个异构体，并分别保留；不要默默选定其中一个。
seed 不是优化结构、过渡态或连接关系证明；构象和分子间接近方式另行计算探索。

## 参考

- [name_resolution.zh-CN.md](references/name_resolution.zh-CN.md)：查询、配置和来源。
- [structure_input.zh-CN.md](references/structure_input.zh-CN.md)：分子图、seed 和反应检查。

- [reaction_mapping.zh-CN.md](references/reaction_mapping.zh-CN.md): 原子映射与反应图检查。
