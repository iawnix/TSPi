---
name: tspi-qbics
description: 判断 QBICS 工作流在科学上是否合适，并在执行前发现是否存在已注册的可运行 capability。
---

# TSPi QBICS

[English version](SKILL.md)

考虑用 QBICS 搜索交叉点或相关结构时使用本 Skill。TSPi 当前没有公开的 QBICS Backend
capability、输入合同或解析合同。

首先查询 `ts_state mode=capabilities capabilityKind=compute`。只有实时目录包含准确的
QBICS capability 时才能继续，并使用目录返回的 role 与参数 schema。若不存在，只能将
预期科学目的、所需电子态、输入、预期输出和验证标准作为方法建议；不得虚构 capability
名称、构造 `ts_calc` 请求、运行任意 shell，或声称 TSPi 可以执行 QBICS。

未来只有在具备确定性 Backend adapter、不可变输入准备、声明的输出、解析合同、任务
验证与测试后，QBICS 集成才可执行。
