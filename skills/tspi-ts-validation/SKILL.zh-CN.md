---
name: tspi-ts-validation
description: 根据鞍点、目标振动模式、结构、电子态与立体化学证据验证过渡态候选。
---

# TSPi 过渡态验证

[English version](SKILL.md)

使用本 Skill 判断候选结构能否作为可信的过渡态。候选生成与 IRC 端点归属是独立任务。

核验优化与驻点证据、经典一阶鞍点所需的唯一相关虚频、沿所提成键变化的位移、电荷与
多重度、电子态一致性、原子映射、几何和立体化学。必须检查原始输出和振动向量；正常
终止或单个负频本身不充分。

将每个已核验属性记录为粒度明确的 FactFinding，将歧义、缺失检查、竞争振动模式、
污染或结构不匹配记录为 IssueFinding。Finding 不会自动设置 Node 或 Claim 状态。只有
明确验收条件需要留下评估时才使用 Gate。

鞍点与振动模式证据见
[transition_state_validation.md](references/transition_state_validation.md)，路径计算后的
盆地身份判据见 [connectivity_validation.md](references/connectivity_validation.md)，映射、
对齐与立体化学比较见 [structure_validation.md](references/structure_validation.md)。
