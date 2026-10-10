---
name: chemical-input
description: 将化学名称、描述或给定结构转成分子图和初始几何，优先使用 PubChem/OPSIN，查询无结果时由 Agent 推断并检查结构；按研究需要准备反应映射。
---

# 化学输入

[English version](SKILL.md)

为用户的研究准备可用结构。随结果保存原始输入、选用结构、来源、电荷和多重度。

## 从输入到计算

1. 用户已提供明确结构（如 SMILES）时直接采用。名称先用 `chemical.resolve@1`
   依次尝试 PubChem、OPSIN；安装配置显式指定的解析器优先级仍然生效。
   保留原始名称，必要时用 `--lookup-name` 提供翻译或规范化的查询名称。
2. 查询没有得到可用结构，包括服务不可用、配置缺失时，由当前 Agent 根据用户描述
   推断候选 SMILES。将候选标为 `source=llm`，简要记录选择依据和相关假设，交给
   `chemical.resolve-candidates@1` 检查。这个步骤在本地处理候选，不重复网络查询。
3. 根据结构检查结果修正解析、价态、电荷或多重度问题。有多个合理结构时，结合任务
   选择工作结构并说明依据，或在研究范围内分支探索；适合时枚举未指定的立体化学。
   只有信息不足以选择有用研究方案时才询问用户；查询失败本身应转入推断。
4. 用 `chemical.seed@1` 生成初始几何，继续用户要求的优化、单点能或反应研究。
   候选来源用于记录研究依据，不增加后续计算前的确认步骤。

通过通用 executor CLI 准备请求，将返回的文件及摘要交给 `job_start`。
所选目标的 `structure` Python 绑定提供 RDKit。收集 Job 的 JSON 和几何文件作为研究材料。

```text
"$CORAGENT_PYTHON" -m research_agent.application.executors --config "$CORAGENT_JOB_CONFIG" --environment local --executor chemical.resolve --version 1 --output prepared/lookup.json -- --name '乙醇' --lookup-name ethanol
"$CORAGENT_PYTHON" -m research_agent.application.executors --config "$CORAGENT_JOB_CONFIG" --environment local --executor chemical.resolve-candidates --version 1 --input candidates=inputs/candidates.json --output prepared/candidates.json
"$CORAGENT_PYTHON" -m research_agent.application.executors --config "$CORAGENT_JOB_CONFIG" --environment local --executor chemical.seed --version 1 --output prepared/seed.json -- --smiles CCO --charge 0 --multiplicity 1
```

给定或修改后的 SMILES 需要检查时使用 `chemical.inspect@1`；已收集的候选结果包含相关
检查时无需重复。初始几何用于启动计算，检查计算输出后再报告所得结果。

## 反应与结构对照

任务需要反应物/产物原子映射时使用 `chemical.reaction@1`，检查组成、电荷及显式映射，
并用 `--transformation` 提供预期成断键变化。单分子优化和单点计算无需反应映射。

把选用的目标结构登记为 Artifact，研究需要时用 `chemical.compare@1` 对照计算后结构。
在研究记录中引用检查结果及来源结构，解释影响研究的差异。

## 参考

- [name_resolution.zh-CN.md](references/name_resolution.zh-CN.md)：查询、推断候选格式和结果字段。
- [structure_input.zh-CN.md](references/structure_input.zh-CN.md)：分子图检查、几何生成和结构对照。
- [reaction_mapping.zh-CN.md](references/reaction_mapping.zh-CN.md)：原子映射与反应图检查。
