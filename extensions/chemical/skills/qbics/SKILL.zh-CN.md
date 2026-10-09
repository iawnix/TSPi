---
name: qbics
description: 判断 QBICS 的适用性，核实已安装命令、输入与验证需求后执行有界研究 Job。
---

# TSPi QBICS

[English version](SKILL.md)

考虑用 QBICS 搜索交叉点或相关结构时使用本 Skill。当前包不内置 QBICS 准备或解析 runner；
这不能说明所选本地或远端环境是否安装了 QBICS。

检查安装绑定、程序文档或有界 help/version 输出，核实预期科学任务、电子态、输入格式、
资源、必需文件及结果解释。若有可用命令或共享 runner，暂存显式输入并通过通用
`job_start` 执行，保留输出和执行回执，无需科学 workflow registry。不要编造命令行参数，
也不要把通用平台探测当作 QBICS 已就绪。

缺少执行或验证环节时，明确具体缺口并继续独立的已授权工作。未知能力应记为未核实；
本 Skill 缺少脚本本身不是执行失败，也不是科学结果。

临时包装脚本通过通用准备器的 `--script` 和明确的 `--backend` 提交，见[方法选择](../method-selection/SKILL.zh-CN.md)。此路径记录脚本、环境、输入和输出。本 Skill 提供科学方法指导，当前没有内置该方法的执行入口。
